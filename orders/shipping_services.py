import requests
import re
import json
from .models import Order, BostaCity, BostaDistrict, Product
from .khazenly_service import KhazenlyService  # <--- Import the new service

# Import the new Aramex Service
from orders.aramex_service import AramexService

def create_bosta_shipment(order: Order):
    print("---  Bosta Shipment Creation Started ---")
    
    api_key = order.brand.delivery_api_key
    if not api_key:
        print("DEBUG (Bosta): FAILED. Brand is missing a Bosta API key.")
        return False

    customer_bosta_city = order.customer.bosta_city
    if not customer_bosta_city:
        print(f"ERROR (Bosta): Customer for order {order.id} does not have a matched Bosta city (governorate). Cannot create shipment.")
        return False
    
    try:
        customer_bosta_district = BostaDistrict.objects.filter(city=customer_bosta_city, name=order.customer.district).first()
    except BostaDistrict.DoesNotExist:
        print(f"ERROR (Bosta): Could not find a BostaDistrict matching name '{order.customer.district}' in city '{customer_bosta_city.name}'.")
        return False
    
    pickup_location = order.brand.default_pickup_location
    if not pickup_location or not pickup_location.bosta_district or not pickup_location.bosta_city:
        print(f"DEBUG (Bosta): FAILED. Brand '{order.brand.name}' is missing a fully configured default pickup location.")
        return False
    
    # --- BOSTA PRODUCTS LOGIC ---
    order_items = order.items.all()
    if not order_items.exists():
        print(f"ERROR (Bosta): Order {order.id} has no items. Cannot create shipment.")
        return False

    first_item = order_items.first()
    
    product_info_list = []
    try:
        for item in order_items:
            product_in_db = Product.objects.get(name__iexact=item.product_name)
            if not product_in_db.bosta_id:
                print(f"ERROR (Bosta): Product '{item.product_name}' in database is missing a bosta_id.")
                return False
                
            product_info_list.append({
                "_id": product_in_db.bosta_id,
                "quantity": item.quantity,
                "productType": "forward"
            })
            
    except Product.DoesNotExist as e:
        print(f"ERROR (Bosta): A product in the order was not found in the local database: {e}. Cannot get Bosta product ID.")
        return False

    print(f"DEBUG (Bosta): Using API Key starting with '{api_key[:4]}'...")
    api_url = "https://app.bosta.co/api/v2/deliveries?apiVersion=1"
    headers = {"Authorization": api_key}
    
    customer_phone = order.customer.phone
    if customer_phone.startswith('+2'):
        customer_phone = customer_phone[2:]

    product_lines = [f"{item.quantity}x {item.product_name}" + (f" ({item.size})" if item.size else "") for item in order_items]
    products_string = ", ".join(product_lines)

    payload = {
        "type": 10,
        "cod": float(order.total_cost),
        "businessReference": str(order.external_id or order.id),
        "productInfo": product_info_list,
        "goodsInfo": {
            "amount": float(first_item.price) 
        },
        "receiver": {
            "firstName": order.customer.first_name,
            "lastName": order.customer.last_name,
            "phone": customer_phone,
            "email": order.customer.email
        },
        "dropOffAddress": {
            "cityId": customer_bosta_city.bosta_id,
            "districtId": customer_bosta_district.bosta_id,
            "firstLine": order.customer.address,
            "secondLine": order.customer.apartment or "",
        },
        "pickupAddress": {
            "cityId": pickup_location.bosta_city.bosta_id,
            "districtId": pickup_location.bosta_district.bosta_id,
            "firstLine": pickup_location.address_line
        },
        "returnAddress": {
            "cityId": pickup_location.bosta_city.bosta_id,
            "districtId": pickup_location.bosta_district.bosta_id,
            "firstLine": pickup_location.address_line
        },
        "notes": f"Contents: {products_string}. Order for {order.customer.first_name}."
    }

    print("DEBUG (Bosta): Sending payload to Bosta...")
    
    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        
        response_data = data.get("data", {})
        tracking_number = response_data.get("trackingNumber")
        
        if tracking_number:
            order.tracking_number = tracking_number
            order.save(update_fields=['tracking_number'])
            print(f"SUCCESS (Bosta): Shipment created. Tracking #: {tracking_number}")
        else:
            print("WARNING (Bosta): API response did not include a tracking number.")
        
        return True
            
    except requests.exceptions.RequestException as e:
        print(f"ERROR (Bosta): API call failed: {e}")
        if e.response is not None:
            print(f"ERROR (Bosta): Response Body: {e.response.text}")
        return False


def send_order_to_delivery_company(order: Order):
    """
    Central router that sends the order to the correct courier based on Brand settings.
    """
    # 1. Validation
    if not order.brand.delivery_company:
        print(f"ERROR: Brand '{order.brand.name}' has no delivery company selected.")
        return False

    company = order.brand.delivery_company.lower()
    print(f"DEBUG: Routing Order {order.id} to {company.upper()}...")

    # 2. Route to Bosta
    if company == 'bosta':
        return create_bosta_shipment(order)
        
    # 3. Route to Aramex
    elif company == 'aramex':
        try:
            # Initialize service (credentials pulled from Brand -> AramexConfiguration)
            service = AramexService(brand=order.brand)
            
            # Call the create method
            success, tracking_number, label_url = service.create_shipment(order)
            
            if success and tracking_number:
                # Save the tracking number
                order.tracking_number = tracking_number
                order.save(update_fields=['tracking_number'])
                
                print(f"SUCCESS (Aramex): Order {order.id} created! Tracking: {tracking_number}")
                if label_url:
                    print(f"Label URL: {label_url}")
                return True
            else:
                print(f"FAILED (Aramex): Could not create shipment for Order {order.id}")
                return False
            

        except Exception as e:
            print(f"EXCEPTION (Aramex): Integration failed for Order {order.id}: {e}")
            return False
            
    
    elif company == 'khazenly':
        try:
            service = KhazenlyService(brand=order.brand)
            success, tracking_number = service.create_order(order)
            
            if success:
                order.tracking_number = tracking_number
                order.save(update_fields=['tracking_number'])
                print(f"SUCCESS (Khazenly): Order {order.id} created! Tracking: {tracking_number}")
                return True
            else:
                print(f"FAILED (Khazenly): Could not create order {order.id}")
                return False
        except Exception as e:
            print(f"EXCEPTION (Khazenly): {e}")
            return False
            
    else:
        print(f"ERROR: Unknown delivery company {company}")
        return False
    
   