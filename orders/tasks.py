# in orders/tasks.py

from background_task import background
import requests
import re
import json 
from django.conf import settings
from .models import Order

@background(schedule=2)
def send_delayed_whatsapp(order_id):
    """
    A background task to send the WhatsApp confirmation message after a delay.
    """
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        print(f"TASK FAILED: Order with ID {order_id} not found.")
        return

    # If order is not pending, don't send a message (e.g., already confirmed/cancelled)
    if order.status != 'pending':
        print(f"TASK SKIPPED: Order {order_id} is already in status '{order.status}'.")
        return

    api_token = settings.WHATSAPP_API_TOKEN
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    template_name = settings.WHATSAPP_TEMPLATE_NAME

    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    
    # --- NEW PHONE NORMALIZATION LOGIC ---
    # 1. Clean all non-numeric characters
    customer_phone = re.sub(r'\D', '', order.customer.phone)
    
    # 2. Check if it's an Egyptian number and format it
    if customer_phone.startswith('20'):
        # Already in the correct format (e.g., 201090092111)
        pass
    elif customer_phone.startswith('01'):
        # Common Egyptian format (e.g., 01090092111)
        # Replace the leading 0 with 20
        customer_phone = '2' + customer_phone
    elif len(customer_phone) == 10 and customer_phone.startswith('1'):
        # Other common format (e.g., 1090092111, missing the 0)
        # Add 20 to the front
        customer_phone = '20' + customer_phone
    else:
        # If it's some other format, assume it's missing the prefix and add it.
        # This will catch numbers like "1090092111"
        if not customer_phone.startswith('2'):
             customer_phone = '20' + customer_phone
             
    print(f"DEBUG: Normalized phone number to: {customer_phone}")
    # --- END OF NEW LOGIC ---


    product_lines = []
    for item in order.items.all():
        if item.quantity > 1:
            line = f"{item.quantity} {item.product_name}"
        else:
            line = item.product_name
        product_lines.append(line)
    
    products_string = " | ".join(product_lines)

    customer_name = order.customer.first_name or "Valued Customer"
    order_number = str(order.external_id) if order.external_id else str(order.id)
    products_list = products_string or "Your items"
    brand_name = order.brand.name or "Our Brand"

    payload = {
        "messaging_product": "whatsapp", "to": customer_phone, "type": "template",
        "template": { "name": template_name, "language": {"code": "en"},
            "components": [
                {"type": "body", "parameters": [
                    {"type": "text", "text": brand_name},
                    {"type": "text", "text": brand_name},
                    {"type": "text", "text": str(order.total_cost)},
                    {"type": "text", "text": order_number},
                    {"type": "text", "text": customer_name},
                    {"type": "text", "text": products_list},
                ]},
                {"type": "button", "sub_type": "quick_reply", "index": "0", "parameters": [{"type": "payload", "payload": f"confirm_order_{order.id}"}]},
                {"type": "button", "sub_type": "quick_reply", "index": "1", "parameters": [{"type": "payload", "payload": f"cancel_order_{order.id}"}]}
            ]
        }
    }

    print(f"BACKGROUND TASK RUNNING: Sending WhatsApp message for order {order_id}...")

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"WhatsApp message sent successfully for order {order_id}!")
    except requests.exceptions.RequestException as e:
        if e.response is not None:
            try:
                error_data = e.response.json() 
                error_code = error_data.get("error", {}).get("code")
                
                if error_code == 131026:
                    print(f"TASK FAILED: Order {order_id} - Phone number {order.customer.phone} is not on WhatsApp.")
                    order.status = "failed" 
                    order.save(update_fields=['status'])
                else:
                    print(f"Error sending WhatsApp for order {order_id}: {e.response.text}")
            except json.JSONDecodeError:
                print(f"Error sending WhatsApp for order {order_id} (non-JSON response): {e.response.text}")
        else:
            print(f"Error sending WhatsApp for order {order_id}: {e}")