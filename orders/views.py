# in orders/views.py

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
from .models import Brand, Order, Customer, BostaCity, BostaDistrict
from .adapters import adapt_incoming_order
from .models import *
from .serializers import *
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