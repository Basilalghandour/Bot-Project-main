# in adapters.py

from decimal import Decimal, InvalidOperation
from .models import Customer

# --- NEW MAPPING DICTIONARY ---
# This dictionary translates Shopify's governorate names to Bosta's official names.
# The keys MUST be lowercase. The values are the exact names Bosta expects.
SHOPIFY_TO_BOSTA_CITY_MAP = {
    # Shopify Name (lowercase) -> Bosta Official Name
    "al sharkia": "Sharqia",
    "as sharqiyah": "Sharqia",
    "el sharkia": "Sharqia",
    "al qalyubia": "El Kalioubia",
    "el kalioubia": "El Kalioubia",
    "qalyubia": "El Kalioubia",
    "al dakahliyah": "Dakahlia",
    "el dakahleya": "Dakahlia",
    "dakahlia": "Dakahlia",
    "menofia": "Monufia",
    "al minufiyah": "Monufia",
    "monufia": "Monufia",
    "beni suef": "Bani Suif",
    "kafr al-sheikh": "Kafr Alsheikh",
    "kafr el sheikh": "Kafr Alsheikh",
    "port said": "Port Said",
    "qena": "Qena",
    "red sea": "Red Sea",
    "sohag": "Sohag",
    "south sinai": "South Sinai",
    "suez": "Suez",
    "6th of october": "Giza", # Special case, mapping to Giza
    # --- Standard mappings from Bosta's list ---
    "alexandria": "Alexandria",
    "assuit": "Assuit",
    "aswan": "Aswan",
    "behira": "Behira",
    "cairo": "Cairo",
    "damietta": "Damietta",
    "fayoum": "Fayoum",
    "gharbia": "Gharbia",
    "giza": "Giza",
    "ismailia": "Ismailia",
    "luxor": "Luxor",
    "matrouh": "Matrouh",
    "menya": "Menya",
    "new valley": "New Valley",
    "north coast": "North Coast",
    "north sinai": "North Sinai",
}


def _to_decimal(value, default=Decimal("0.00")):
    # ... (no changes here)
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def adapt_shopify_order(data, brand=None):
    customer_data = data.get("customer", {}) or {}
    shipping_address = data.get("shipping_address", {}) or {}
    
    # --- NORMALIZATION LOGIC ---
    # 1. Get the raw governorate name from Shopify's payload.
    raw_governorate = shipping_address.get("province") or customer_data.get("province") or ""

    # 2. Look it up in our mapping dictionary.
    # .get() will return the Bosta name if found, or the original name if not.
    normalized_governorate = SHOPIFY_TO_BOSTA_CITY_MAP.get(
        raw_governorate.lower().strip(),  # Look up the lowercase, stripped version
        raw_governorate  # Fallback to the original name if no mapping is found
    )
    # --- END NORMALIZATION LOGIC ---

    email = customer_data.get("email") or ""
    first_name = shipping_address.get("first_name") or ""
    last_name = shipping_address.get("last_name") or ""
    phone = shipping_address.get("phone") or customer_data.get("phone") or ""
    address = shipping_address.get("address1") or ""
    apartment = shipping_address.get("address2") or ""
    city = shipping_address.get("city") or ""
    # state is now normalized_governorate
    country = shipping_address.get("country") or ""
    postal_code = shipping_address.get("zip") or None

    # Adapt order items
    items = []
    for li in data.get("line_items", []) or []:
        qty = li.get("quantity") or li.get("qty") or 1
        price = li.get("price") or li.get("price_per_unit") or li.get("total") or li.get("subtotal") or 0
        
        size = li.get("variant_title")

        items.append({
            "product_name": li.get("name") or li.get("title") or li.get("product_id") or "item",
            "quantity": int(qty),
            "price": str(_to_decimal(price)),
            "size": size,
        })
    
    shipping_lines = data.get("shipping_lines", [])
    shipping_cost = "0.00"
    if shipping_lines and isinstance(shipping_lines, list) and shipping_lines[0].get("price"):
        shipping_cost = shipping_lines[0].get("price")
    total_cost = data.get("total_price", "0.00")

    adapted = {
        "customer": {
            "first_name": first_name, "last_name": last_name, "email": email, "phone": phone,
            "address": address, "apartment": apartment, "city": city, 
            "state": normalized_governorate, # <-- USE THE NORMALIZED NAME HERE
            "country": country, "postal_code": postal_code,
        },
        "items": items,
        "shipping_cost": str(_to_decimal(shipping_cost)),
        "total_cost": str(_to_decimal(total_cost)),
    }
    customer_facing_id = data.get("order_number") or data.get("name") or data.get("id")
    if customer_facing_id:
        adapted["external_id"] = str(customer_facing_id).replace("#", "")
    return adapted


def adapt_woocommerce_order(data, brand=None):
    # This logic can also be applied to WooCommerce if needed
    shipping = data.get("shipping", {}) or {}
    billing = data.get("billing", {}) or {}

    raw_governorate = shipping.get("state") or billing.get("state") or ""
    normalized_governorate = SHOPIFY_TO_BOSTA_CITY_MAP.get(
        raw_governorate.lower().strip(),
        raw_governorate
    )

    first_name = shipping.get("first_name") or billing.get("first_name") or ""
    last_name = shipping.get("last_name") or billing.get("last_name")  or ""
    email = billing.get("email") or ""
    phone = shipping.get("phone") or billing.get("phone") or ""
    address = shipping.get("address_1") or billing.get("address_1") or ""
    apartment = shipping.get("address_2") or billing.get("address_2") or ""
    city = shipping.get("city") or billing.get("city") or ""
    # state is now normalized_governorate
    country = shipping.get("country") or billing.get("country") or ""
    postal_code = shipping.get("postcode") or billing.get("postcode") or None
    shipping_cost = data.get("shipping_total", "0.00")
    total_cost = data.get("total", "0.00")

    # Adapt order items with unit price
    items = []
    for li in data.get("line_items", []) or []:
        qty = li.get("quantity") or li.get("qty") or 1
        total = _to_decimal(li.get("total") or 0)
        unit_price = (total / qty) if qty else total
        
        size = None
        for meta in li.get("meta_data", []):
            if meta.get("key", "").lower() == 'size':
                size = meta.get("value")
                break

        items.append({
            "product_name": li.get("name") or li.get("title") or "item",
            "quantity": int(qty),
            "price": str(unit_price),
            "size": size,
        })

    adapted = {
        "customer": {
            "first_name": first_name, "last_name": last_name, "email": email, "phone": phone,
            "address": address, "apartment": apartment, "city": city,
            "state": normalized_governorate, # <-- USE THE NORMALIZED NAME HERE
            "country": country, "postal_code": postal_code,
        },
        "items": items,
        "shipping_cost": str(_to_decimal(shipping_cost)),
        "total_cost": str(_to_decimal(total_cost)),
    }
    if "id" in data:
        adapted["external_id"] = str(data.get("id"))
    return adapted


def adapt_incoming_order(data, brand=None):
    # ... (no changes needed in this function)
    if isinstance(data, dict):
        if "line_items" in data and "customer" in data:
            return adapt_shopify_order(data, brand)
        if "line_items" in data and "billing" in data:
            return adapt_woocommerce_order(data, brand)
        if "billing" in data and "line_items" in data:
            return adapt_woocommerce_order(data, brand)
        if "items" in data and isinstance(data.get("items"), list):
            for item in data.get("items", []):
                item.setdefault("size", None)
            return {
                "customer": data.get("customer", {}),
                "items": data.get("items", []),
                "external_id": str(data.get("external_id")) if data.get("external_id") else None,
                "shipping_cost": str(_to_decimal(data.get("shipping_cost", "0.00"))),
                "total_cost": str(_to_decimal(data.get("total_cost", "0.00"))),
            }
    return {
        "customer": data.get("customer", {}),
        "items": [],
        "external_id": str(data.get("id")) if data.get("id") else None,
        "shipping_cost": "0.00",
        "total_cost": "0.00",
    }

