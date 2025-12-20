# in orders/views.py
import re # <--- Add this import at the very top of views.py
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
from django.conf import settings
import json
from django.contrib.auth import update_session_auth_hash # <--- Add this
from django.contrib.auth.decorators import login_required
import random
from .tasks import send_delayed_whatsapp
from .shipping_services import send_order_to_delivery_company
from .district_matching import find_best_district_match
from .models import Brand, Order, Customer, BostaCity, BostaDistrict
from .adapters import adapt_incoming_order
from .services import send_whatsapp_template_message # <--- Import the new function
from .models import *
from .serializers import *
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login
from django.contrib import messages
from .models import Brand
from django.contrib.auth.decorators import login_required



class BrandViewSet(viewsets.ModelViewSet):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    lookup_field = "webhook_id"
    lookup_value_regex = "[0-9a-f-]{32}"


class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer

    def get_queryset(self):
        brand_webhook_id = self.kwargs.get("brand_webhook_id")
        if brand_webhook_id:
            brand = get_object_or_404(Brand, webhook_id=brand_webhook_id)
            return Order.objects.filter(brand=brand)
        return Order.objects.all()


    @csrf_exempt
    def create(self, request, *args, **kwargs):
        brand_webhook_id = self.kwargs.get("brand_webhook_id")
        brand = get_object_or_404(Brand, webhook_id=brand_webhook_id)
        
        adapted = adapt_incoming_order(request.data, brand=brand)
        customer_data = adapted.pop("customer", {})

        # Raw inputs from Shopify/Store
        raw_governorate = customer_data.get("state", "")
        raw_district = customer_data.get("city", "") # 'city' from adapter is often the district

        final_city_name = raw_governorate
        final_district_name = raw_district
        bosta_city_link = None

        # --- CONDITIONAL VALIDATION ---
        # Only run Bosta matching if the brand is NOT Aramex
        if brand.delivery_company in ['aramex', 'khazenly']:
            print(f"DEBUG: Brand '{brand.name}' uses {brand.delivery_company}. Skipping Bosta validation.")
            # For Aramex, we accept the raw data as-is. 
            # The 'AramexService' will handle the name correction (e.g. Bani Suif -> Beni Suef) later.
            
        else:           
            # --- BOSTA STRICT LOGIC ---
            # 1. Match Governorate (City)
            try:
                bosta_city_link = BostaCity.objects.get(name__iexact=raw_governorate)
                final_city_name = bosta_city_link.name # Use the clean DB name
                print(f"DEBUG: Automatically matched governorate '{raw_governorate}' to Bosta City: {bosta_city_link.name}")
            except BostaCity.DoesNotExist:
                print(f"WARNING: Governorate '{raw_governorate}' not found in Bosta cities.")
                return Response(
                    {"error": f"Governorate '{raw_governorate}' is not a valid city for Bosta."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 2. Match District
            matched_district = find_best_district_match(raw_district, bosta_city_link)

            if matched_district:
                final_district_name = matched_district.name
            else:
                # 3. Fallback Logic
                try:
                    default_district_name = f"Default - {bosta_city_link.name}"
                    matched_district = BostaDistrict.objects.get(city=bosta_city_link, name=default_district_name)
                    final_district_name = matched_district.name
                    print(f"DISTRICT_MATCH: FALLBACK. Using default district '{matched_district.name}'.")
                except BostaDistrict.DoesNotExist:
                    error_message = f"Could not validate district '{raw_district}' in '{raw_governorate}' and no default found."
                    print(f"REJECTING ORDER: {error_message}")
                    return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

        # --- CREATE CUSTOMER ---
        customer = Customer.objects.create(
                 first_name=customer_data.get("first_name", ""),
                 last_name=customer_data.get("last_name", ""),
                 email=customer_data.get("email", ""),
                 phone=customer_data.get("phone", ""),
                 address=customer_data.get("address", ""),
                 apartment=customer_data.get("apartment", ""),
                 
                 # Use the resolved names (Raw for Aramex, Cleaned for Bosta)
                 city=final_city_name,  
                 district=final_district_name,
                 
                 bosta_city=bosta_city_link, # Can be None for Aramex
                 country=customer_data.get("country", ""),
                 postal_code=customer_data.get("postal_code", ""),
        )

        serializer = self.get_serializer(data=adapted, context={'customer': customer})
        serializer.is_valid(raise_exception=True)
        order = serializer.save(brand=brand)

        if order:
            send_delayed_whatsapp(order.id)
            print(f"Order {order.id} created. WhatsApp message scheduled.")
        
        out_serializer = self.get_serializer(order)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)    


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    queryset = Customer.objects.all()


class CustomerOrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer

    def get_queryset(self):
        customer_id = self.kwargs.get("customer_pk")
        get_object_or_404(Customer, pk=customer_id)
        return Order.objects.filter(customer_id=customer_id)    


class ConfirmationViewSet(viewsets.ModelViewSet):
    queryset = Confirmation.objects.all()
    serializer_class = ConfirmationSerializer


class DashboardViewSet(viewsets.ModelViewSet):
    queryset = Brand.objects.all()
    http_method_names = ['get']

    def list(self, request, *args, **kwargs):
        webhook_id = self.kwargs.get('brand_webhook_id')      
        brand = get_object_or_404(Brand, webhook_id=webhook_id)
        orders = Order.objects.filter(brand=brand).order_by('-created_at')

        metrics = {
            'total_orders': orders.count(),
            'confirmed': orders.filter(status='confirmed').count(),
            'pending': orders.filter(status='pending').count(),
            'cancelled': orders.filter(status='cancelled').count(),
        }

        context = { "brand": brand, "orders": orders, "metrics": metrics, }
        return render(request, "dashboard.html", context)


@csrf_exempt
def whatsapp_webhook(request):
    # GET request for verification
    if request.method == "GET":
        verify_token = settings.WHATSAPP_VERIFY_TOKEN
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if mode == "subscribe" and token == verify_token:
            print("WEBHOOK_VERIFIED")
            return HttpResponse(challenge, status=200)
        else:
            print("WEBHOOK_VERIFICATION_FAILED")
            return HttpResponse("error, verification failed", status=403)

    # POST request handler
    if request.method == "POST":
        data = json.loads(request.body)
        print("--- WHATSAPP WEBHOOK RECEIVED ---")
        print(json.dumps(data, indent=2))

        if "object" in data and data.get("object") == "whatsapp_business_account":
            try:
                message = data["entry"][0]["changes"][0]["value"]["messages"][0]
                
                if message.get("type") == "button":
                    button_payload = message["button"]["payload"]
                    action, _, order_id = button_payload.partition('_order_')

                    try:
                        order = Order.objects.get(id=int(order_id))
                        
                        if order.status == 'pending':
                            reply_message = ""
                            
                            if action == "confirm":
                                order.status = "confirmed"
                                reply_message = "تم تأكيد طلبك بنجاح وسيتم ترتيب الشحن ✅"
                                
                            elif action == "cancel":
                                order.status = "cancelled"
                                reply_message = "تم الغاء طلبك…❌\nلعمل طلب اخر يمكنك زيارة الموقع"
                            
                            order.save()
                            print(f"SUCCESS: Order {order_id} status updated to '{order.status}' in the database.")

                            # Trigger shipment if confirmed
                            if action == "confirm":
                                print(f"DEBUG: Triggering shipment creation for confirmed order {order_id}...")
                                send_order_to_delivery_company(order)

                            # Send follow-up message
                            if reply_message:
                                send_whatsapp_template_message(order.customer.phone, reply_message)
                        
                        else:
                            print(f"DEBUG: Ignoring duplicate reply for Order {order_id}.")

                    except Order.DoesNotExist:
                        print(f"ERROR: Order with ID {order_id} not found.")

            except (IndexError, KeyError):
                pass 

        print("--- WHATSAPP WEBHOOK END ---")
        return HttpResponse("success", status=200)
    
    return HttpResponse("Unsupported method", status=405)
def validate_step1(request):
    """
    AJAX Endpoint to check duplicates.
    """
    if request.method == 'GET':
        email = request.GET.get('email', '').strip()
        phone = request.GET.get('phone', '').strip()
        errors = {}
        
        # 1. Email Check
        if email and User.objects.filter(username=email).exists():
            errors['email'] = "An account with this email already exists."
            
        # 2. Phone Check (Smart Matching)
        if phone:
            # Clean input: remove spaces, dashes, etc.
            clean_input = re.sub(r'\D', '', phone) 
            
            # Check against direct match first
            if Brand.objects.filter(phone_number=phone).exists():
                errors['phone'] = "This phone number is already registered."
            else:
                # Check for "contains" logic or other formats if needed
                # For now, let's try finding it by the cleaned version if you store them cleaned
                # Or check if any existing number *contains* this number
                if Brand.objects.filter(phone_number__icontains=clean_input).exists():
                     errors['phone'] = "This phone number is already registered."

        return JsonResponse(errors)
    return JsonResponse({}, status=400)

# In orders/views.py

def landing_page(request):
    """
    Renders the main landing page for Confirm It.
    """
    return render(request, "landing.html")

# In orders/views.py

def login_page(request):
    """Renders the simple Login page."""
    return render(request, "login.html")

def signup_page(request):
    """Renders the simple Sign Up page."""
    return render(request, "signup.html")


def signup_page(request):
    """Handles Brand Sign Up logic."""
    if request.method == 'POST':
        # 1. Get Form Data
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        # Note: We still get phone from POST for form repopulation, 
        # but we will use the SESSION phone for the database.
        phone_input = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        brand_name = request.POST.get('brand_name', '').strip()
        website = request.POST.get('website', '').strip()
        delivery_company = request.POST.get('delivery_company', '')

        form_data = {
            'first_name': first_name, 'last_name': last_name, 'email': email,
            'phone': phone_input, 'brand_name': brand_name, 
            'website': website, 'delivery_company': delivery_company,
        }
        
        errors = {}

        # --- VALIDATIONS ---
        if not first_name: errors['first_name'] = "First Name is required."
        if not last_name: errors['last_name'] = "Last Name is required."
        if not email: errors['email'] = "Email is required."
        if not brand_name: errors['brand_name'] = "Brand Name is required."
        if not delivery_company: errors['delivery_company'] = "Select a delivery partner."
        
        # Security: Check Verification
        verified_phone = request.session.get('signup_phone')
        is_verified = request.session.get('is_phone_verified')

        if not is_verified or not verified_phone:
            messages.error(request, "Please verify your phone number via WhatsApp first.")
            return render(request, "signup.html", {'form_data': form_data})

        # Password Checks
        if len(password) < 8:
            errors['password'] = "Min 8 chars required."
        if password != confirm_password:
            errors['confirm_password'] = "Passwords do not match."

        # Duplicate Checks
        if User.objects.filter(username=email).exists():
            errors['email'] = "This email is already registered."
        if Brand.objects.filter(phone_number=verified_phone).exists():
            errors['phone'] = "This phone number is already registered."

        if errors:
            return render(request, "signup.html", {'form_data': form_data, 'errors': errors})

        # --- CREATE ACCOUNT ---
        try:
            # 1. Create User
            user = User.objects.create_user(
                username=email, 
                email=email, 
                password=password,
                first_name=first_name,
                last_name=last_name
            )
            
            # 2. Create Brand (Use VERIFIED phone, not input)
            Brand.objects.create(
                user=user,
                name=brand_name,
                website=website,
                contact_email=email,
                phone_number=verified_phone, # <--- SECURE
                delivery_company=delivery_company
            )

            # 3. Log In Immediately
            login(request, user)
            
            # 4. Cleanup Session
            request.session.pop('signup_otp', None)
            request.session.pop('signup_phone', None)
            request.session.pop('is_phone_verified', None)

            # 5. Redirect to Dashboard
            # 'home' maps to landing_page, which auto-shows dashboard for logged-in users
            return redirect('home') 

        except Exception as e:
            messages.error(request, f"System Error: {e}")
            return render(request, "signup.html", {'form_data': form_data})

    return render(request, "signup.html")


def login_page(request):
    """Handles Brand Login logic with Field Errors."""
    if request.method == 'POST':
        email = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        errors = {}
        
        if not email:
            errors['username'] = "Email is required."
        if not password:
            errors['password'] = "Password is required."
            
        if not errors:
            user = authenticate(request, username=email, password=password)
            if user is not None:
                login(request, user)
                return redirect('home')
            else:
                # Attach invalid credentials error to the password field or a general error
                errors['detail'] = "Invalid email or password."

        return render(request, "login.html", {'username': email, 'errors': errors})
    
    return render(request, "login.html")


def landing_page(request):
    # If user is logged in, show them their dashboard
    if request.user.is_authenticated:
        # Try to get the brand associated with this user
        try:
            brand = request.user.brand
            
            # Fetch stats specific to this brand
            orders = Order.objects.filter(brand=brand).order_by('-created_at')
            metrics = {
                'total_orders': orders.count(),
                'confirmed': orders.filter(status='confirmed').count(),
                'pending': orders.filter(status='pending').count(),
                'cancelled': orders.filter(status='cancelled').count(),
            }
            password_errors = request.session.pop('password_errors', {})
            show_password_modal = request.session.pop('show_password_modal', False)
            
            context = { "brand": brand, "orders": orders, "metrics": metrics,"password_errors": password_errors,
                       "show_password_modal": show_password_modal }
            return render(request, "dashboard.html", context)
            
        except Brand.DoesNotExist:
            # User exists but has no brand (shouldn't happen with correct signup flow)
            return HttpResponse("User has no Brand profile.", status=400)
            
    # If not logged in, show the Landing Page
    return render(request, "landing.html")


@login_required
def change_password(request):
    if request.method == 'POST':
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        user = request.user
        errors = {}

        # --- VALIDATION ---
        if not user.check_password(current_password):
            errors['current_password'] = "Incorrect current password."
        
        if new_password != confirm_password:
            errors['confirm_password'] = "Passwords do not match."
            
        if len(new_password) < 8:
            errors['new_password'] = "Password must be at least 8 characters."

        # --- IF ERRORS EXIST ---
        if errors:
            # 1. SAVE ERRORS TO SESSION
            request.session['password_errors'] = errors
            request.session['show_password_modal'] = True
            
            # 2. REDIRECT BACK
            # Note: Ensure this URL matches your dashboard's URL name or path
            return redirect('/?tab=settings') 

        # --- SUCCESS ---
        user.set_password(new_password)
        user.save()
        update_session_auth_hash(request, user) # Critical: Prevents logging out
        messages.success(request, "Password updated successfully!")
        
        return redirect('/?tab=settings')

    return redirect('/')


@login_required
def update_profile(request):
    if request.method == 'POST':
        user = request.user
        brand = user.brand

        # 1. Get Data
        new_brand_name = request.POST.get('brand_name', '').strip()
        new_website = request.POST.get('website', '').strip()
        new_email = request.POST.get('email', '').strip()
        new_delivery = request.POST.get('delivery_company', '').strip()

        # 2. Validations
        if not new_brand_name:
            messages.error(request, "Brand Name cannot be empty.")
            return redirect('/?tab=settings')
        
        if not new_email:
            messages.error(request, "Email cannot be empty.")
            return redirect('/?tab=settings')

        # Check for duplicates (exclude current user)
        if new_email != user.email:
            if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
                messages.error(request, "This email address is already in use.")
                return redirect('/?tab=settings')

        # 3. Update User (Auth)
        if new_email != user.email:
            user.email = new_email
            user.username = new_email 
            user.save()

        # 4. Update Brand Information
        brand.name = new_brand_name
        brand.website = new_website
        
        # --- NEW: SYNC CONTACT EMAIL ---
        brand.contact_email = new_email 
        
        if new_delivery: 
            brand.delivery_company = new_delivery
        
        brand.save()

        messages.success(request, "Profile information updated successfully!")
        return redirect('/?tab=settings')

    return redirect('/')


# In orders/views.py

def send_otp_view(request):
    email = request.GET.get('email', '').strip()
    raw_phone = request.GET.get('phone', '').strip()
    
    # --- 1. CLEAN PHONE NUMBER ---
    # Remove spaces, dashes, and plus signs
    phone = raw_phone.replace(" ", "").replace("-", "").replace("+", "")
    
    # Logic: Only fix if it starts with '0' (e.g., 010... -> 2010...)
    if phone.startswith("0"):
        phone = "2" + phone
        
    # NOTE: We REMOVED the logic that blindly added "2" to other numbers.
    # Now, if someone types "1090092111" (10 digits), it enters validation as-is and fails.

    # --- 2. VALIDATE LENGTH ---
    # Egyptian numbers (International format 2010...) must be exactly 12 digits.
    if len(phone) != 12:
        return JsonResponse({'errors': {'phone': "Invalid phone number."}}, status=400)
    
    # Check digits only
    if not phone.isdigit():
        return JsonResponse({'errors': {'phone': "Phone number must contain only digits."}}, status=400)

    errors = {}

    # --- 3. DUPLICATE CHECKS ---
    if User.objects.filter(username=email).exists():
        errors['email'] = "This email is already registered."
    
    if Brand.objects.filter(phone_number=phone).exists():
        errors['phone'] = "This phone number is already registered."

    if errors:
        return JsonResponse({'errors': errors}, status=400)

    # --- 4. GENERATE OTP ---
    otp_code = str(random.randint(1000, 9999))
    request.session['signup_otp'] = otp_code
    request.session['signup_phone'] = phone
    
    print(f"DEBUG: Generated OTP for {phone}: {otp_code}")

    # --- 5. SEND WHATSAPP TEMPLATE ---
    try:
        template_name = "verification_code" 
        
        # Explicitly passing language_code='en_US' based on your template
        response_data = send_whatsapp_template_message(
            phone, 
            template_name, 
            [otp_code], 
            language_code='en_US'
        )
        
        if 'error' in response_data:
            print(f"WHATSAPP API ERROR: {response_data}")
            return JsonResponse({'error': 'WhatsApp API Error'}, status=500)
            
        print(f"DEBUG: WhatsApp Response: {response_data}")

    except Exception as e:
        print(f"Error sending WhatsApp OTP: {e}")
        return JsonResponse({'error': 'Failed to send WhatsApp message'}, status=500)

    return JsonResponse({'status': 'sent'})


def verify_otp_view(request):
    """
    Checks if the entered code matches the session OTP.
    """
    entered_code = request.GET.get('code', '').strip()
    session_code = request.session.get('signup_otp')
    
    if not session_code:
        return JsonResponse({'error': 'OTP expired. Please resend.'}, status=400)

    if entered_code == session_code:
        # Mark as verified
        request.session['is_phone_verified'] = True
        return JsonResponse({'status': 'verified'})
    else:
        return JsonResponse({'error': 'Incorrect code. Please try again.'}, status=400)
    


@login_required
def send_change_phone_otp(request):
    """
    Sends OTP to a NEW phone number for an existing user.
    """
    raw_phone = request.GET.get('phone', '').strip()
    
    # --- 1. CLEAN PHONE NUMBER (Same logic as Signup) ---
    phone = raw_phone.replace(" ", "").replace("-", "").replace("+", "")
    if phone.startswith("0"):
        phone = "2" + phone
        
    # --- 2. VALIDATE ---
    if len(phone) != 12:
        return JsonResponse({'error': "Invalid phone number."}, status=400)
    if not phone.isdigit():
        return JsonResponse({'error': "Phone number must contain only digits."}, status=400)
        
    # --- 3. DUPLICATE CHECK ---
    # Check if taken by ANYONE ELSE (exclude current user in case they re-enter same number)
    if Brand.objects.filter(phone_number=phone).exclude(user=request.user).exists():
        return JsonResponse({'error': "This phone number is already registered to another account."}, status=400)

    # --- 4. GENERATE & SEND ---
    otp_code = str(random.randint(1000, 9999))
    
    # Store in session with UNIQUE keys (different from signup keys)
    request.session['change_phone_otp'] = otp_code
    request.session['change_phone_new_number'] = phone
    
    print(f"DEBUG: Generated Change-Phone OTP for {phone}: {otp_code}")

    try:
        template_name = "verification_code" 
        send_whatsapp_template_message(phone, template_name, [otp_code], language_code='en_US')
    except Exception as e:
        print(f"Error sending WhatsApp OTP: {e}")
        return JsonResponse({'error': 'Failed to send WhatsApp message'}, status=500)

    return JsonResponse({'status': 'sent'})


@login_required
def verify_change_phone_otp(request):
    """
    Verifies the OTP and IMMEDIATELY updates the database.
    """
    entered_code = request.GET.get('code', '').strip()
    session_code = request.session.get('change_phone_otp')
    new_phone = request.session.get('change_phone_new_number')
    
    if not session_code or not new_phone:
        return JsonResponse({'error': 'Session expired. Please request a new code.'}, status=400)

    if entered_code == session_code:
        # --- SUCCESS: UPDATE DB ---
        brand = request.user.brand
        brand.phone_number = new_phone
        brand.save()
        
        # Clear session
        request.session.pop('change_phone_otp', None)
        request.session.pop('change_phone_new_number', None)
        
        return JsonResponse({'status': 'verified', 'message': 'Phone number updated successfully!'})
    else:
        return JsonResponse({'error': 'Incorrect code.'}, status=400)
    


@login_required
def send_change_phone_otp(request):
    """
    Sends OTP to a NEW phone number for an existing user.
    Uses EXACTLY the same cleaning/validation logic as signup.
    """
    raw_phone = request.GET.get('phone', '').strip()
    
    # --- 1. CLEAN PHONE NUMBER (Exact same logic as Signup) ---
    phone = raw_phone.replace(" ", "").replace("-", "").replace("+", "")
    
    # Logic: Only fix if it starts with '0' (e.g., 010... -> 2010...)
    if phone.startswith("0"):
        phone = "2" + phone

    # --- 2. VALIDATE ---
    if len(phone) != 12:
        return JsonResponse({'error': "Invalid phone number."}, status=400)
    
    if not phone.isdigit():
        return JsonResponse({'error': "Phone number must contain only digits."}, status=400)
        
    # --- 3. DUPLICATE CHECK ---
    # Check if taken by ANYONE ELSE (exclude current user so they can re-verify their own if needed)
    if Brand.objects.filter(phone_number=phone).exclude(user=request.user).exists():
        return JsonResponse({'error': "This phone number is already registered to another account."}, status=400)

    # --- 4. GENERATE & SEND ---
    otp_code = str(random.randint(1000, 9999))
    
    # Store in session with UNIQUE keys for this specific action
    request.session['change_phone_otp'] = otp_code
    request.session['change_phone_new_number'] = phone
    
    print(f"DEBUG: Generated Change-Phone OTP for {phone}: {otp_code}")

    try:
        template_name = "verification_code" 
        # Ensure language_code matches your template (e.g. 'en_US')
        send_whatsapp_template_message(phone, template_name, [otp_code], language_code='en_US')
    except Exception as e:
        print(f"Error sending WhatsApp OTP: {e}")
        return JsonResponse({'error': 'Failed to send WhatsApp message'}, status=500)

    return JsonResponse({'status': 'sent'})


@login_required
def verify_change_phone_otp(request):
    """
    Verifies the OTP and IMMEDIATELY updates the user's Brand.
    """
    entered_code = request.GET.get('code', '').strip()
    session_code = request.session.get('change_phone_otp')
    new_phone = request.session.get('change_phone_new_number')
    
    if not session_code or not new_phone:
        return JsonResponse({'error': 'Session expired. Please request a new code.'}, status=400)

    if entered_code == session_code:
        # --- SUCCESS: UPDATE DB ---
        try:
            brand = request.user.brand
            brand.phone_number = new_phone
            brand.save()
            
            # Clear session
            request.session.pop('change_phone_otp', None)
            request.session.pop('change_phone_new_number', None)
            
            # --- NEW: Add Success Message for the next page load ---
            messages.success(request, "Phone number updated successfully!")
            
            return JsonResponse({'status': 'verified'})
        except Brand.DoesNotExist:
             return JsonResponse({'error': 'Brand profile not found.'}, status=400)
    else:
        return JsonResponse({'error': 'Incorrect code.'}, status=400)