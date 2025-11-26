# in orders/views.py

# All necessary imports are combined at the top of the file
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.conf import settings
import json
from .tasks import send_delayed_whatsapp
from .shipping_services import send_order_to_delivery_company
from .district_matching import find_best_district_match
from .models import Brand, Order, Customer, BostaCity, BostaDistrict # ensure BostaDistrict is imported
from .adapters import adapt_incoming_order
from .models import *
from .serializers import *
# --- IMPORT THE NEW TEXT MESSAGE FUNCTION ---
from .services import send_whatsapp_text_message


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

        # --- GOVERNORATE (CITY) MATCHING ---
        governorate_name = customer_data.get("state", "")
        bosta_city_link = None
        try:
            bosta_city_link = BostaCity.objects.get(name__iexact=governorate_name)
            print(f"DEBUG: Automatically matched governorate '{governorate_name}' to Bosta City: {bosta_city_link.name}")
        except BostaCity.DoesNotExist:
            print(f"WARNING: Governorate '{governorate_name}' not found in Bosta cities.")
            # If the main governorate/city is not found, we cannot proceed.
            return Response(
                {"error": f"Governorate '{governorate_name}' is not a valid city."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- DISTRICT MATCHING LOGIC ---
        user_district_name = customer_data.get("city", "") # 'city' from adapter is the district
        matched_district = find_best_district_match(user_district_name, bosta_city_link)

        # --- FALLBACK LOGIC START ---
        if not matched_district:
            # If no specific match, try to find the default for this city
            try:
                # Construct the default district name we agreed on (e.g., "Default - Cairo")
                default_district_name = f"Default - {bosta_city_link.name}"
                matched_district = BostaDistrict.objects.get(city=bosta_city_link, name=default_district_name)
                print(f"DISTRICT_MATCH: FALLBACK. Using default district '{matched_district.name}' for city '{bosta_city_link.name}'.")
            except BostaDistrict.DoesNotExist:
                # This will happen if we forgot to add a default row in the DB for this city
                error_message = f"Could not validate district '{user_district_name}' in '{governorate_name}' and no default district was found."
                print(f"REJECTING ORDER: {error_message}")
                return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)
        # --- FALLBACK LOGIC END ---

        # By this point, 'matched_district' is either the best match or the default.
        customer = Customer.objects.create(
                 first_name=customer_data.get("first_name", ""),
                 last_name=customer_data.get("last_name", ""),
                 email=customer_data.get("email", ""),
                 phone=customer_data.get("phone", ""),
                 address=customer_data.get("address", ""),
                 apartment=customer_data.get("apartment", ""),
                 city=governorate_name,  # Governorate (e.g., "Cairo")
                 district=matched_district.name, # USE THE OFFICIAL, MATCHED, OR DEFAULT NAME
                 bosta_city=bosta_city_link,
                 country=customer_data.get("country", ""),
                 postal_code=customer_data.get("postal_code", ""),
        )

        serializer = self.get_serializer(data=adapted, context={'customer': customer})
        serializer.is_valid(raise_exception=True)
        order = serializer.save(brand=brand)

        if order:
            # The background task is scheduled here
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


# in orders/views.py

# in orders/views.py

@csrf_exempt
# in orders/views.py

@csrf_exempt
def whatsapp_webhook(request):
    # GET request for verification (no changes here)
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

    # POST request handler (updated with more prints)
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
                            # --- UPDATED PRINT STATEMENT AS REQUESTED ---
                            print(f"SUCCESS: Order {order_id} status updated to '{order.status}' in the database.")

                            # If the order was just confirmed, send it to the delivery company
                            if action == "confirm":
                                print(f"DEBUG: Triggering shipment creation for confirmed order {order_id}...")
                                send_order_to_delivery_company(order)

                            # Send the follow-up message to the customer
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