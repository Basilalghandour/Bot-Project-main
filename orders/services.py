# in orders/services.py

import requests
import re
from django.conf import settings

def send_whatsapp_text_message(phone_number, message):
    """
    A simple function to send a plain text message via WhatsApp.
    """
    api_token = settings.WHATSAPP_API_TOKEN
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    
    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    
    # Sanitize the phone number
    clean_phone_number = re.sub(r'\D', '', phone_number)

    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone_number,
        "type": "text",
        "text": {
            "body": message
        }
    }

    print(f"Sending follow-up text message to {clean_phone_number}...")
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print("Follow-up message sent successfully.")
        return True
    except requests.exceptions.RequestException as e:
        if e.response is not None:
            print(f"Error sending follow-up message: {e.response.text}")
        return False