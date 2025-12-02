import requests
import time
import re
import difflib
from datetime import datetime, timedelta
from django.conf import settings
# Import your new models
from orders.models import AramexCity, AramexDistrict

class AramexService:
    """
    Service class to handle Aramex SOAP API interactions.
    """
    PRODUCTION_URL = "https://ws.aramex.net/ShippingAPI.V2/Shipping/Service_1_0.svc"
    
    def __init__(self, brand):
        """
        Initialize with credentials from the Brand's AramexConfiguration.
        """
        if not hasattr(brand, 'aramex_configuration'):
            raise ValueError(f"Brand '{brand.name}' does not have an Aramex Configuration set up.")
        
        config = brand.aramex_configuration
        self.username = config.username
        self.password = config.password
        self.account_number = config.account_number
        self.account_pin = config.account_pin
        self.account_entity = config.account_entity
        self.account_country_code = config.account_country_code
        self.version = config.version

    # --- SMART MATCHING LOGIC START ---
    def _normalize_text(self, text):
        """
        Cleans and standardizes text (logic from district_matching.py).
        """
        if not isinstance(text, str): return ""
        text = text.lower().strip()
        text = text.replace('3', 'a').replace('7', 'h').replace('5', 'kh').replace('8', 'gh')
        
        if text.startswith("al-"): text = text[3:]
        elif text.startswith("el-"): text = text[3:]
        elif text.startswith("al"): text = text[2:]
        elif text.startswith("el"): text = text[2:]
        
        text = re.sub(r'^(ال|أل)', '', text).strip()
        text = re.sub(r'[^a-z0-9\s\u0600-\u06FF]', '', text, flags=re.UNICODE)
        return re.sub(r'\s+', ' ', text).strip()

    def _smart_match(self, input_name, candidates, threshold=0.70):
        """
        Intelligent matching using token comparison and scoring.
        """
        if not input_name or not candidates: return None
        normalized_input = self._normalize_text(input_name)
        input_tokens = set(normalized_input.split())
        if not input_tokens: return None

        best_match_obj = None
        highest_score = 0.0

        for obj in candidates:
            db_name = obj.name
            normalized_db_name = self._normalize_text(db_name)
            if not normalized_db_name: continue
            db_tokens = set(normalized_db_name.split())
            if not db_tokens: continue

            total_similarity = 0
            for in_token in input_tokens:
                best_match_for_token = difflib.get_close_matches(in_token, db_tokens, n=1, cutoff=0.4)
                if best_match_for_token:
                    similarity = difflib.SequenceMatcher(None, in_token, best_match_for_token[0]).ratio()
                    total_similarity += similarity
            
            score = total_similarity / len(input_tokens)
            if normalized_input and normalized_db_name and normalized_input[0] == normalized_db_name[0]:
                score *= 1.15

            if score > highest_score:
                highest_score = score
                best_match_obj = obj

        if best_match_obj and highest_score >= threshold:
            print(f"ARAMEX SMART MATCH: '{input_name}' -> '{best_match_obj.name}' (Score: {highest_score:.2f})")
            return best_match_obj
        return None

    def _get_validated_city(self, user_city, user_district):
        # 1. Match Governorate
        all_cities = list(AramexCity.objects.all())
        matched_city_obj = self._smart_match(user_city, all_cities, threshold=0.80)
        
        if not matched_city_obj:
            print(f"ARAMEX WARNING: Could not match city '{user_city}'. Using raw.")
            return user_city
            
        matched_city_name = matched_city_obj.name

        # 2. Cairo Special Logic
        if matched_city_name.lower() == "cairo":
            print(f"ARAMEX: Detected Cairo. Attempting smart match for district '{user_district}'...")
            cairo_districts = list(AramexDistrict.objects.filter(city=matched_city_obj))
            matched_district_obj = self._smart_match(user_district, cairo_districts, threshold=0.65)
            
            if matched_district_obj:
                return matched_district_obj.name 
            else:
                return "Heliopolis" # Fallback

        return matched_city_name
    # --- SMART MATCHING LOGIC END ---

    def create_shipment(self, order):
        """
        Creates a shipment in Aramex for the given Order object.
        Returns: (success, tracking_number, label_url)
        """
        try:
            # --- 1. PREPARE DATA ---
            
            # Shipper (Sender) Data
            pickup_loc = order.brand.default_pickup_location
            if not pickup_loc:
                raise ValueError(f"Brand '{order.brand.name}' has no Default Pickup Location.")

            shipper_line1 = pickup_loc.address_line
            shipper_line2 = pickup_loc.bosta_district.name if pickup_loc.bosta_district else ""
            shipper_city = pickup_loc.bosta_city.name if pickup_loc.bosta_city else "Cairo"
            
            # Consignee (Customer) Data
            customer = order.customer
            if not customer:
                raise ValueError(f"Order {order.id} has no customer attached.")
            
            # --- APPLY SMART MATCHING LOGIC HERE ---
            final_api_city = self._get_validated_city(customer.city, customer.district)
            # ---------------------------------------

            customer_phone = self._sanitize_phone(customer.phone)
            customer_name = f"{customer.first_name} {customer.last_name}"
            
            # Dates (Now + 1 Hour)
            shipping_date = datetime.now() + timedelta(hours=1)
            shipping_date_str = shipping_date.strftime('%Y-%m-%dT%H:%M:%S')
            due_date = datetime.now() + timedelta(days=3)
            due_date_str = due_date.strftime('%Y-%m-%dT%H:%M:%S')

            # Unique HAWB
            foreign_hawb = f"{order.external_id or order.id}-{int(time.time())}"

            # Items Description
            items_desc = " | ".join([f"{item.quantity}x {item.product_name}" for item in order.items.all()])
            if not items_desc: items_desc = "General Items"
            if len(items_desc) > 200: items_desc = items_desc[:197] + "..."

            # Pieces
            number_of_pieces = sum(item.quantity for item in order.items.all())
            if number_of_pieces < 1: number_of_pieces = 1

            # --- 2. PAYMENT & SERVICE LOGIC (Restored from your file) ---
            # Always E-Commerce (CDS)
            # Always Bill Shipper Account (P/ACCT)
            # Always COD (Value in CashOnDeliveryAmount)
            
            payment_type = "P"
            payment_options = "ACCT"
            product_type = "CDS"
            
            # CRITICAL FIX: Leave Services empty for CDS. The Amount triggers the collection.
            services_string = "" 
            
            cod_amount = f"{order.total_cost:.2f}"
            customs_value = f"{order.total_cost:.2f}"

            # --- 3. CONSTRUCT XML PAYLOAD ---
            xml_payload = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:v1="http://ws.aramex.net/ShippingAPI/v1/">
               <soapenv:Header/>
               <soapenv:Body>
                  <v1:ShipmentCreationRequest>
                     <v1:ClientInfo>
                        <v1:UserName>{self.username}</v1:UserName>
                        <v1:Password>{self.password}</v1:Password>
                        <v1:Version>{self.version}</v1:Version>
                        <v1:AccountNumber>{self.account_number}</v1:AccountNumber>
                        <v1:AccountPin>{self.account_pin}</v1:AccountPin>
                        <v1:AccountEntity>{self.account_entity}</v1:AccountEntity>
                        <v1:AccountCountryCode>{self.account_country_code}</v1:AccountCountryCode>
                     </v1:ClientInfo>

                     <v1:Transaction>
                        <v1:Reference1>{order.id}</v1:Reference1>
                        <v1:Reference2></v1:Reference2>
                        <v1:Reference3></v1:Reference3>
                        <v1:Reference4></v1:Reference4>
                        <v1:Reference5></v1:Reference5>
                     </v1:Transaction>

                     <v1:Shipments>
                        <v1:Shipment>
                           <v1:Shipper>
                              <v1:Reference1>{self.account_number}</v1:Reference1>
                              <v1:Reference2></v1:Reference2>
                              <v1:AccountNumber>{self.account_number}</v1:AccountNumber>
                              <v1:PartyAddress>
                                 <v1:Line1>{shipper_line1}</v1:Line1>
                                 <v1:Line2>{shipper_line2}</v1:Line2>
                                 <v1:Line3></v1:Line3>
                                 <v1:City>{shipper_city}</v1:City>
                                 <v1:StateOrProvinceCode>{shipper_city}</v1:StateOrProvinceCode>
                                 <v1:PostCode>00000</v1:PostCode>
                                 <v1:CountryCode>{self.account_country_code}</v1:CountryCode>
                              </v1:PartyAddress>
                              <v1:Contact>
                                 <v1:Department>Logistics</v1:Department>
                                 <v1:PersonName>{order.brand.name}</v1:PersonName>
                                 <v1:Title></v1:Title>
                                 <v1:CompanyName>{order.brand.name}</v1:CompanyName>
                                 <v1:PhoneNumber1>{order.brand.phone_number or ""}</v1:PhoneNumber1>
                                 <v1:PhoneNumber1Ext></v1:PhoneNumber1Ext>
                                 <v1:PhoneNumber2></v1:PhoneNumber2>
                                 <v1:PhoneNumber2Ext></v1:PhoneNumber2Ext>
                                 <v1:FaxNumber></v1:FaxNumber>
                                 <v1:CellPhone>{order.brand.phone_number or "01000000000"}</v1:CellPhone>
                                 <v1:EmailAddress>{order.brand.contact_email or "logistics@brand.com"}</v1:EmailAddress>
                                 <v1:Type>Business</v1:Type>
                              </v1:Contact>
                           </v1:Shipper>

                           <v1:Consignee>
                              <v1:Reference1>{customer.id}</v1:Reference1>
                              <v1:Reference2></v1:Reference2>
                              <v1:PartyAddress>
                                 <v1:Line1>{customer.address}</v1:Line1>
                                 <v1:Line2>{customer.district or ""}</v1:Line2>
                                 <v1:Line3>{customer.apartment or ""}</v1:Line3>
                                 
                                 <v1:City>{final_api_city}</v1:City>
                                 <v1:StateOrProvinceCode>{final_api_city}</v1:StateOrProvinceCode>
                                 
                                 <v1:PostCode>{customer.postal_code or "00000"}</v1:PostCode>
                                 <v1:CountryCode>EG</v1:CountryCode>
                              </v1:PartyAddress>
                              <v1:Contact>
                                 <v1:Department>Personal</v1:Department>
                                 <v1:PersonName>{customer_name}</v1:PersonName>
                                 <v1:Title></v1:Title>
                                 <v1:CompanyName>{customer_name}</v1:CompanyName>
                                 <v1:PhoneNumber1>{customer_phone}</v1:PhoneNumber1>
                                 <v1:PhoneNumber1Ext></v1:PhoneNumber1Ext>
                                 <v1:PhoneNumber2></v1:PhoneNumber2>
                                 <v1:PhoneNumber2Ext></v1:PhoneNumber2Ext>
                                 <v1:FaxNumber></v1:FaxNumber>
                                 <v1:CellPhone>{customer_phone}</v1:CellPhone>
                                 <v1:EmailAddress>{customer.email}</v1:EmailAddress>
                                 <v1:Type>Individual</v1:Type>
                              </v1:Contact>
                           </v1:Consignee>

                           <v1:ShippingDateTime>{shipping_date_str}</v1:ShippingDateTime>
                           <v1:DueDate>{due_date_str}</v1:DueDate>
                           <v1:Comments>Handle with care</v1:Comments>
                           <v1:PickupLocation>Reception</v1:PickupLocation>
                           <v1:OperationsInstructions>None</v1:OperationsInstructions>
                           <v1:AccountingInstrcutions>None</v1:AccountingInstrcutions>

                           <v1:Details>
                              <v1:Dimensions>
                                 <v1:Length>10</v1:Length>
                                 <v1:Width>10</v1:Width>
                                 <v1:Height>10</v1:Height>
                                 <v1:Unit>CM</v1:Unit>
                              </v1:Dimensions>
                              
                              <v1:ActualWeight>
                                 <v1:Unit>KG</v1:Unit>
                                 <v1:Value>1.0</v1:Value>
                              </v1:ActualWeight>

                              <v1:ChargeableWeight>
                                 <v1:Unit>KG</v1:Unit>
                                 <v1:Value>1.0</v1:Value>
                              </v1:ChargeableWeight>

                              <v1:DescriptionOfGoods>{items_desc}</v1:DescriptionOfGoods>
                              <v1:GoodsOriginCountry>EG</v1:GoodsOriginCountry>
                              
                              <v1:NumberOfPieces>{number_of_pieces}</v1:NumberOfPieces>

                              <v1:ProductGroup>DOM</v1:ProductGroup>
                              <v1:ProductType>{product_type}</v1:ProductType>
                              
                              <v1:PaymentType>{payment_type}</v1:PaymentType>
                              <v1:PaymentOptions>{payment_options}</v1:PaymentOptions>

                              <v1:CustomsValueAmount>
                                  <v1:CurrencyCode>EGP</v1:CurrencyCode>
                                  <v1:Value>{customs_value}</v1:Value>
                              </v1:CustomsValueAmount>

                              <v1:CashOnDeliveryAmount>
                                  <v1:CurrencyCode>EGP</v1:CurrencyCode>
                                  <v1:Value>{cod_amount}</v1:Value>
                              </v1:CashOnDeliveryAmount>

                              <v1:InsuranceAmount>
                                  <v1:CurrencyCode>EGP</v1:CurrencyCode>
                                  <v1:Value>0</v1:Value>
                              </v1:InsuranceAmount>

                              <v1:CashAdditionalAmount>
                                  <v1:CurrencyCode>EGP</v1:CurrencyCode>
                                  <v1:Value>0</v1:Value>
                              </v1:CashAdditionalAmount>

                              <v1:CashAdditionalAmountDescription>None</v1:CashAdditionalAmountDescription>

                              <v1:CollectAmount>
                                  <v1:CurrencyCode>EGP</v1:CurrencyCode>
                                  <v1:Value>0</v1:Value>
                              </v1:CollectAmount>

                              <v1:Services>{services_string}</v1:Services>
                              <v1:Items></v1:Items>
                           </v1:Details>
                           
                           <v1:Attachments></v1:Attachments>
                           <v1:ForeignHAWB>{foreign_hawb}</v1:ForeignHAWB>
                           <v1:TransportType>0</v1:TransportType>
                           <v1:PickupGUID></v1:PickupGUID>
                           <v1:Number></v1:Number>
                        </v1:Shipment>
                     </v1:Shipments>
                     
                     <v1:LabelInfo>
                        <v1:ReportID>9201</v1:ReportID>
                        <v1:ReportType>URL</v1:ReportType>
                     </v1:LabelInfo>
                     
                  </v1:ShipmentCreationRequest>
               </soapenv:Body>
            </soapenv:Envelope>"""

            headers = {
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction': 'http://ws.aramex.net/ShippingAPI/v1/Service_1_0/CreateShipments'
            }

            response = requests.post(self.PRODUCTION_URL, data=xml_payload.encode('utf-8'), headers=headers)
            
            if response.status_code == 200:
                if "<HasErrors>false</HasErrors>" in response.text:
                    try:
                        start = response.text.find("<ID>") + 4
                        end = response.text.find("</ID>")
                        tracking_id = response.text[start:end]
                        
                        label_url = None
                        if "LabelURL" in response.text:
                            l_start = response.text.find("<LabelURL>") + 10
                            l_end = response.text.find("</LabelURL>")
                            label_url = response.text[l_start:l_end]
                            
                        print(f"SUCCESS: Aramex Shipment created. ID: {tracking_id}")
                        return True, tracking_id, label_url
                    except:
                        print("SUCCESS (Parsing Error): Shipment created but couldn't parse ID/Label.")
                        return True, "PARSING_ERROR", None
                else:
                    print(f"ARAMEX API ERROR: {response.text}")
                    return False, None, None
            else:
                print(f"HTTP ERROR: {response.status_code}")
                return False, None, None

        except Exception as e:
            print(f"EXCEPTION: {e}")
            return False, None, None

    def _sanitize_phone(self, phone):
        if not phone: return ""
        phone = re.sub(r'[^0-9+]', '', str(phone))
        if len(phone) == 11 and phone.startswith("01"):
             return phone
        if phone.startswith("+2"):
             return phone[2:]
        return phone