import requests
from django.conf import settings

def send_whatsapp_text_message(phone_number, message):
    """
    Sends a plain text message. 
    (Keep this for your existing order notifications)
    """
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}",
        "Content-Type": "application/json",
    }
    url = f"https://graph.facebook.com/v22.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    data = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {"body": message},
    }
    response = requests.post(url, headers=headers, json=data)
    return response

def send_whatsapp_template_message(to_number, template_name, parameters, language_code="en_US"):
    """
    Sends a Template Message.
    SPECIAL UPDATE: Automatically adds the button parameter for OTP codes.
    """
    url = f"https://graph.facebook.com/v22.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}",
        "Content-Type": "application/json",
    }

    # 1. Prepare Body Component (Standard)
    body_params = [{"type": "text", "text": str(p)} for p in parameters]
    components = [
        {
            "type": "body",
            "parameters": body_params
        }
    ]

    # 2. SPECIAL FIX: If this is the OTP template, add the button component
    # The 'Copy Code' button needs the OTP passed to it specifically.
    if template_name == "verification_code" and parameters:
        components.append({
            "type": "button",
            "sub_type": "url",  # Authentication templates use 'url' type for the code payload
            "index": 0,
            "parameters": [
                {"type": "text", "text": str(parameters[0])} # Pass the OTP code again
            ]
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code 
            },
            "components": components
        }
    }

    response = requests.post(url, headers=headers, json=payload)
    
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"Meta API Error: {response.text}")
        raise e

    return response.json()