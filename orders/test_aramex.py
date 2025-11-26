import requests
import time
from datetime import datetime, timedelta

# 1. Setup Connection
url = "https://ws.aramex.net/ShippingAPI.V2/Shipping/Service_1_0.svc"
headers = {
    'Content-Type': 'text/xml; charset=utf-8',
    'SOAPAction': 'http://ws.aramex.net/ShippingAPI/v1/Service_1_0/CreateShipments'
}

# 2. Dynamic Data
unique_hawb = f"TEST-FULL-{int(time.time())}"
shipping_date = (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')
due_date = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M:%S')

# 3. The COMPLETE Payload (Parts 1-6)
xml_payload = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:v1="http://ws.aramex.net/ShippingAPI/v1/">
   <soapenv:Header/>
   <soapenv:Body>
      <v1:ShipmentCreationRequest>
         <v1:ClientInfo>
            <v1:UserName>basilelghandour@gmail.com</v1:UserName>
            <v1:Password>Ghandour+123</v1:Password>
            <v1:Version>v1.0</v1:Version>
            <v1:AccountNumber>72697312</v1:AccountNumber>
            <v1:AccountPin>915286</v1:AccountPin>
            <v1:AccountEntity>CAI</v1:AccountEntity>
            <v1:AccountCountryCode>EG</v1:AccountCountryCode>
         </v1:ClientInfo>

         <v1:Transaction>
            <v1:Reference1>Test_Full_Order</v1:Reference1>
            <v1:Reference2></v1:Reference2>
            <v1:Reference3></v1:Reference3>
            <v1:Reference4></v1:Reference4>
            <v1:Reference5></v1:Reference5>
         </v1:Transaction>

         <v1:Shipments>
            <v1:Shipment>
               <v1:Shipper>
                  <v1:Reference1>Warehouse_01</v1:Reference1>
                  <v1:Reference2></v1:Reference2>
                  <v1:AccountNumber>72697312</v1:AccountNumber>
                  <v1:PartyAddress>
                     <v1:Line1>123 El Tahrir St</v1:Line1>
                     <v1:Line2>Maadi</v1:Line2> <v1:Line3></v1:Line3>
                     <v1:City>Cairo</v1:City>
                     <v1:StateOrProvinceCode>Cairo</v1:StateOrProvinceCode>
                     <v1:PostCode>11511</v1:PostCode>
                     <v1:CountryCode>EG</v1:CountryCode>
                  </v1:PartyAddress>
                  <v1:Contact>
                     <v1:Department>Logistics</v1:Department>
                     <v1:PersonName>Logistics Manager</v1:PersonName>
                     <v1:Title>Mr</v1:Title>
                     <v1:CompanyName>Confirm It Brand</v1:CompanyName>
                     <v1:PhoneNumber1>01000000000</v1:PhoneNumber1>
                     <v1:PhoneNumber1Ext></v1:PhoneNumber1Ext>
                     <v1:PhoneNumber2></v1:PhoneNumber2>
                     <v1:PhoneNumber2Ext></v1:PhoneNumber2Ext>
                     <v1:FaxNumber></v1:FaxNumber>
                     <v1:CellPhone>01000000000</v1:CellPhone>
                     <v1:EmailAddress>logistics@confirmit.com</v1:EmailAddress>
                     <v1:Type>Business</v1:Type>
                  </v1:Contact>
               </v1:Shipper>

               <v1:Consignee>
                  <v1:Reference1>Cust_100</v1:Reference1>
                  <v1:Reference2></v1:Reference2>
                  <v1:PartyAddress>
                     <v1:Line1>456 Corniche El Nile</v1:Line1>
                     <v1:Line2>Sidi Gaber</v1:Line2> <v1:Line3>Apt 4</v1:Line3>
                     <v1:City>masr egedeeda</v1:City>
                     <v1:StateOrProvinceCode>masr egdeeda</v1:StateOrProvinceCode>
                     <v1:PostCode>21500</v1:PostCode>
                     <v1:CountryCode>EG</v1:CountryCode>
                  </v1:PartyAddress>
                  <v1:Contact>
                     <v1:Department>Personal</v1:Department>
                     <v1:PersonName>Test Customer</v1:PersonName>
                     <v1:Title>Mr</v1:Title>
                     <v1:CompanyName>Test Customer</v1:CompanyName>
                     <v1:PhoneNumber1>01012345678</v1:PhoneNumber1>
                     <v1:PhoneNumber1Ext></v1:PhoneNumber1Ext>
                     <v1:PhoneNumber2></v1:PhoneNumber2>
                     <v1:PhoneNumber2Ext></v1:PhoneNumber2Ext>
                     <v1:FaxNumber></v1:FaxNumber>
                     <v1:CellPhone>01012345678</v1:CellPhone>
                     <v1:EmailAddress>customer@example.com</v1:EmailAddress>
                     <v1:Type>Individual</v1:Type>
                  </v1:Contact>
               </v1:Consignee>

               <v1:ShippingDateTime>{shipping_date}</v1:ShippingDateTime>
               <v1:DueDate>{due_date}</v1:DueDate>
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

                  <v1:DescriptionOfGoods>2x T-Shirt | 1x Pants</v1:DescriptionOfGoods>
                  <v1:GoodsOriginCountry>EG</v1:GoodsOriginCountry>
                  <v1:NumberOfPieces>1</v1:NumberOfPieces>

                  <v1:ProductGroup>DOM</v1:ProductGroup>
                  <v1:ProductType>CDS</v1:ProductType>
                  <v1:PaymentType>P</v1:PaymentType> <v1:PaymentOptions></v1:PaymentOptions>

                  <v1:CustomsValueAmount>
                      <v1:CurrencyCode>EGP</v1:CurrencyCode>
                      <v1:Value>500.00</v1:Value>
                  </v1:CustomsValueAmount>

                  <v1:CashOnDeliveryAmount>
                      <v1:CurrencyCode>EGP</v1:CurrencyCode>
                      <v1:Value>500.00</v1:Value>
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

                  <v1:Services></v1:Services> <v1:Items></v1:Items>
               </v1:Details>

               <v1:Attachments></v1:Attachments>
               <v1:ForeignHAWB>{unique_hawb}</v1:ForeignHAWB>
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

# 4. Send Request
try:
    print("Sending request to Aramex...")
    response = requests.post(url, data=xml_payload.encode('utf-8'), headers=headers)
    
    print("Status Code:", response.status_code)
    
    if response.status_code == 200 and "<HasErrors>false</HasErrors>" in response.text:
        print("SUCCESS: Shipment Created!")
        
        # Extract ID
        if "<ID>" in response.text:
            start = response.text.find("<ID>") + 4
            end = response.text.find("</ID>")
            print("Shipment ID:", response.text[start:end])

        # Extract Label
        if "LabelURL" in response.text:
            start = response.text.find("<LabelURL>") + 10
            end = response.text.find("</LabelURL>")
            print("Label URL:", response.text[start:end])
    else:
        print("FAILED.")
        print("Response Body:", response.text)

except Exception as e:
    print("Error:", e)