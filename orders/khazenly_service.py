import requests
import re
import difflib
from datetime import timedelta
from django.utils import timezone
from .models import KhazenlyConfiguration, KhazenlyCity

class KhazenlyService:
    # Endpoints
    STAGING_AUTH_URL = "https://khazenly4--test.sandbox.my.site.com/selfservice/services/oauth2/token"
    STAGING_API_BASE = "https://khazenly4--test.sandbox.my.salesforce.com/services/apexrest/api"
    
    PRODUCTION_AUTH_URL = "https://integrations.khazenly.com/selfservice/services/oauth2/token"
    PRODUCTION_API_BASE = "https://integrations.khazenly.com/selfservice/services/apexrest/api"

    def __init__(self, brand):
        try:
            self.config = brand.khazenly_configuration
        except KhazenlyConfiguration.DoesNotExist:
            raise ValueError(f"Brand '{brand.name}' has no Khazenly Configuration.")

        if self.config.is_live:
            self.auth_url = self.PRODUCTION_AUTH_URL
            self.api_url = self.PRODUCTION_API_BASE
        else:
            self.auth_url = self.STAGING_AUTH_URL
            self.api_url = self.STAGING_API_BASE

    # --- SMART MATCHING LOGIC ---
    def _normalize_text(self, text):
        """
        Cleans and standardizes text for comparison.
        """
        if not isinstance(text, str): return ""
        text = text.lower().strip()
        
        # Common replacements
        text = text.replace('3', 'a').replace('7', 'h').replace('5', 'kh').replace('8', 'gh')
        
        # Handle prefixes
        if text.startswith("al-"): text = text[3:]
        elif text.startswith("el-"): text = text[3:]
        elif text.startswith("al"): text = text[2:]
        elif text.startswith("el"): text = text[2:]
        
        # Remove Arabic definite article and non-alphanumeric chars
        text = re.sub(r'^(ال|أل)', '', text).strip()
        text = re.sub(r'[^a-z0-9\s\u0600-\u06FF]', '', text, flags=re.UNICODE)
        return re.sub(r'\s+', ' ', text).strip()

    def _smart_match(self, input_name, threshold=0.70):
        """
        Finds the best matching KhazenlyCity from the database.
        """
        if not input_name: return None
        
        candidates = list(KhazenlyCity.objects.all())
        if not candidates:
            print("KHAZENLY WARNING: No cities found in KhazenlyCity database. Please add them in Admin.")
            return None

        normalized_input = self._normalize_text(input_name)
        input_tokens = set(normalized_input.split())
        if not input_tokens: return None

        best_match_obj = None
        highest_score = 0.0

        for city_obj in candidates:
            db_name = city_obj.name
            normalized_db_name = self._normalize_text(db_name)
            if not normalized_db_name: continue
            
            db_tokens = set(normalized_db_name.split())
            if not db_tokens: continue

            total_similarity = 0
            for in_token in input_tokens:
                # Find best matching token in the DB name
                best_match_for_token = difflib.get_close_matches(in_token, db_tokens, n=1, cutoff=0.4)
                if best_match_for_token:
                    similarity = difflib.SequenceMatcher(None, in_token, best_match_for_token[0]).ratio()
                    total_similarity += similarity
            
            # Average score based on number of input tokens
            score = total_similarity / len(input_tokens)
            
            # Bonus for matching first letter
            if normalized_input and normalized_db_name and normalized_input[0] == normalized_db_name[0]:
                score *= 1.15

            if score > highest_score:
                highest_score = score
                best_match_obj = city_obj

        if best_match_obj and highest_score >= threshold:
            print(f"KHAZENLY MATCH: '{input_name}' -> '{best_match_obj.name}' (Score: {highest_score:.2f})")
            return best_match_obj.name
        
        print(f"KHAZENLY NO MATCH: '{input_name}' (Best: {highest_score:.2f})")
        return None

    # --- TOKEN MANAGEMENT ---
    def _get_valid_token(self):
        # Increased buffer to 60 minutes for safety
        safety_buffer = timedelta(minutes=60)
        
        if (self.config.access_token and 
            self.config.token_expiry and 
            self.config.token_expiry > timezone.now() + safety_buffer):
            return self.config.access_token
            
        print("KHAZENLY: Token is expired or expiring soon (< 60 mins). Refreshing...")
        return self._refresh_access_token()

    def _refresh_access_token(self):
        print("KHAZENLY: Refreshing Access Token...")
        if not self.config.refresh_token:
            raise ValueError("Refresh Token is missing.")

        params = {
            "grant_type": "refresh_token",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "refresh_token": self.config.refresh_token
        }

        try:
            response = requests.post(self.auth_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            self.config.access_token = data.get("access_token")
            # Set expiry to 2 hours from now to force frequent refreshes if needed
            self.config.token_expiry = timezone.now() + timedelta(hours=2) 
            self.config.save()
            return self.config.access_token
            
        except requests.exceptions.RequestException as e:
            print(f"KHAZENLY AUTH ERROR: {e}")
            if e.response is not None:
                print(f"Response: {e.response.text}")
            raise

    # --- ORDER CREATION ---
    def create_order(self, order):
        token = self._get_valid_token()
        customer = order.customer
        
        # 1. SMART CITY MATCHING
        khazenly_city = self._smart_match(customer.city)
        if not khazenly_city:
            print(f"KHAZENLY: Could not match city '{customer.city}'. Defaulting to 'Cairo'.")
            khazenly_city = "Cairo"
        
        # 2. Payment Info
        is_cod = order.total_cost > 0
        payment_method = "Cash-on-Delivery (COD)" if is_cod else "Pre-Paid"
        payment_status = "pending" if is_cod else "paid"
        
        # 3. Build Items List
        line_items = []
        items_total_price = 0.0
        
        for item in order.items.all():
            price = float(item.price)
            sku_val = item.sku if item.sku else item.product_name
            
            line_items.append({
                "itemName": item.product_name,
                "sku": sku_val, 
                "price": price,
                "quantity": item.quantity,
                "discountAmount": 0
            })
            items_total_price += (price * item.quantity)

        # 4. Auto-Balancing Math
        # Calculate shipping as the difference to make the invoice match exactly
        target_collection_amount = float(order.total_cost)
        calculated_shipping = target_collection_amount - items_total_price
        if calculated_shipping < 0: calculated_shipping = 0

        # 5. Address Formatting (District BEFORE Address)
        # Note: We check if district exists to avoid a dangling comma
        if customer.district:
            full_address = f"{customer.district}, {customer.address}"
        else:
            full_address = customer.address

        # 6. Payload Construction
        payload = {
            "Order": {
                "orderId": str(order.id),
                "orderNumber": str(order.external_id or order.id),
                "storeName": self.config.store_url,
                "storeCurrency": "EGP",
                "totalAmount": target_collection_amount,
                "invoiceTotalAmount": target_collection_amount,
                "taxAmount": 0,
                "discountAmount": 0,
                "shippingFees": calculated_shipping,
                "paymentMethod": payment_method,
                "paymentStatus": payment_status,
                "weight": 1.0
            },
            "Customer": {
                "customerName": f"{customer.first_name} {customer.last_name}",
                "Tel": customer.phone,
                "address1": full_address,  # Sends "Maadi, 123 Street"
                "address2": customer.apartment or "",
                "City": khazenly_city,
                "Country": "Egypt"
            },
            "LineItems": line_items 
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        print(f"KHAZENLY: Sending Order {order.id} to {self.api_url}...")
        
        try:
            response = requests.post(f"{self.api_url}/CreateOrder", json=payload, headers=headers)
            response.raise_for_status()
            
            result = response.json()
            
            # Khazenly returns success via "resultCode": 0 or "result": "Success"
            if result.get("resultCode") == 0 or result.get("result") == "Success":
                tracking_no = result.get("order", {}).get("salesOrderNumber")
                print(f"KHAZENLY SUCCESS: Tracking # {tracking_no}")
                return True, tracking_no
            else:
                print(f"KHAZENLY LOGIC ERROR: {result}")
                return False, None
            
        except requests.exceptions.RequestException as e:
            print(f"KHAZENLY API ERROR: {e}")
            if e.response is not None:
                print(f"Response Body: {e.response.text}")
            return False, None