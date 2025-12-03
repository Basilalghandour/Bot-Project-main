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

from .tasks import send_delayed_whatsapp
from .shipping_services import send_order_to_delivery_company
from .district_matching import find_best_district_match
from .models import Brand, Order, Customer, BostaCity, BostaDistrict
from .adapters import adapt_incoming_order
from .models import *
from .serializers import *
from .services import send_whatsapp_text_message
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
        if brand.delivery_company == 'aramex':
            print(f"DEBUG: Brand '{brand.name}' uses Aramex. Skipping Bosta validation.")
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
                                send_whatsapp_text_message(order.customer.phone, reply_message)
                        
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
    """Handles Brand Sign Up logic with Field-Specific Validations."""
    if request.method == 'POST':
        # 1. Get data
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        brand_name = request.POST.get('brand_name', '').strip()
        website = request.POST.get('website', '').strip()
        delivery_company = request.POST.get('delivery_company', '')

        # Store data to repopulate form on error
        form_data = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'phone': phone,
            'brand_name': brand_name,
            'website': website,
            'delivery_company': delivery_company,
        }
        
        errors = {}

        # --- VALIDATIONS ---
        
        # Step 1 Validations
        if not first_name:
            errors['first_name'] = "First Name is required."
        if not last_name:
            errors['last_name'] = "Last Name is required."
        if not email:
            errors['email'] = "Email Address is required."
        if not phone:
            errors['phone'] = "Phone Number is required."
        if not password:
            errors['password'] = "Password is required."
        
        # Step 2 Validations
        if not brand_name:
            errors['brand_name'] = "Brand Name is required."
        if not delivery_company:
            errors['delivery_company'] = "Please select a delivery partner."

        # Logic Checks
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if email and not re.match(email_regex, email):
            errors['email'] = "Enter a valid email address."

        if phone and not re.match(r'^\+?[\d\s-]{10,15}$', phone):
            errors['phone'] = "Enter a valid phone number."

        if password:
            if len(password) < 8:
                errors['password'] = "Must be at least 8 characters."
            elif not any(char.isalpha() for char in password):
                errors['password'] = "Must contain at least one letter."

        if confirm_password != password:
            errors['confirm_password'] = "Passwords do not match."
        
        if 'email' not in errors:
            if User.objects.filter(username=email).exists():
                errors['email'] = "An account with this email already exists."
        if 'phone' not in errors:
            if Brand.objects.filter(phone_number=phone).exists():
                errors['phone'] = "This phone number is already registered."

        # --- IF ERRORS EXIST ---
        if errors:
            return render(request, "signup.html", {'form_data': form_data, 'errors': errors})

        # --- SUCCESS ---
        try:
            # Create User with First/Last Name
            user = User.objects.create_user(
                username=email, 
                email=email, 
                password=password,
                first_name=first_name,
                last_name=last_name
            )
            user.save()

            # Create Brand
            Brand.objects.create(
                user=user,
                name=brand_name,
                website=website,
                contact_email=email,
                phone_number=phone,
                delivery_company=delivery_company
            )

            login(request, user)
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
            
            context = { "brand": brand, "orders": orders, "metrics": metrics }
            return render(request, "dashboard.html", context)
            
        except Brand.DoesNotExist:
            # User exists but has no brand (shouldn't happen with correct signup flow)
            return HttpResponse("User has no Brand profile.", status=400)
            
    # If not logged in, show the Landing Page
    return render(request, "landing.html")