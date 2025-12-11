from django.db import models
from decimal import Decimal
from django.contrib.auth.models import User  # <--- Import User
import uuid
class PickupLocation(models.Model):
    brand = models.ForeignKey("Brand", on_delete=models.CASCADE, related_name="pickup_locations")
    name = models.CharField(max_length=100) # e.g., "Main Warehouse"
    address_line = models.CharField(max_length=255)
    
    # --- ADDED FOREIGN KEY TO CITY AS REQUESTED ---
    bosta_city = models.ForeignKey("BostaCity", on_delete=models.SET_NULL, null=True, blank=True)
    bosta_district = models.ForeignKey("BostaDistrict", on_delete=models.SET_NULL, null=True, blank=True)


from django.db import models
from django.contrib.auth.models import User  # <--- Import User
import uuid

# ... (PickupLocation model stays the same)

class Brand(models.Model):
    # Link Brand to a User Account
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='brand', null=True, blank=True)
    
    name = models.CharField(max_length=100)
    website = models.URLField(blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    webhook_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    
    # Updated choices to match your HTML dropdown
    DELIVERY_CHOICES = [
        ('bosta', 'Bosta'),
        ('aramex', 'Aramex'),
        ('khazenly', 'Khazenly'),
        ('other', 'Other / Not Listed'),
    ]
    
    delivery_company = models.CharField(
        max_length=50, 
        choices=DELIVERY_CHOICES, 
        blank=True, 
        null=True
    )
    delivery_api_key = models.CharField(max_length=255, blank=True, null=True)
    default_pickup_location = models.ForeignKey('PickupLocation', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    def __str__(self):
        return self.name


class Order(models.Model):
    external_id = models.CharField(max_length=255, blank=True, null=True, unique=True)  
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="orders")
    customer = models.ForeignKey("Customer", on_delete=models.CASCADE, related_name="orders", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=[("pending", "Pending"), ("confirmed", "Confirmed"), ("cancelled", "Cancelled")],
        default="pending")
    responded_at = models.DateTimeField(blank=True, null=True)  
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    tracking_number = models.CharField(max_length=255, blank=True, null=True)
      
    
    @property
    def total_price(self):
        """Calculates the total price of all items in the order."""
        return sum(item.price * item.quantity for item in self.items.all())

    def __str__(self):
        return f"Order #{self.id} - {self.customer}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product_name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    size = models.CharField(max_length=50, blank=True, null=True)
    sku = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.product_name} (x{self.quantity})"
    
    
class Customer(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    address = models.CharField(max_length=255)
    apartment = models.CharField(max_length=100, null=True, blank=True)
    district = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=50)
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    bosta_city = models.ForeignKey("BostaCity", on_delete=models.SET_NULL, null=True, blank=True)


    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
# in Bot-Project/orders/models.py

# ... (at the end of the file, before or after the Bosta models)

class Product(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=255, help_text="The product name from Shopify/WooCommerce")
    variant = models.CharField(max_length=255, null=True, blank=True, help_text="The variant name, e.g., 'S', 'Red', 'Large'")
    bosta_id = models.CharField(max_length=100, unique=True, null=True, blank=True, help_text="The unique _id from Bosta's List Products API")

    def __str__(self):
        if self.variant:
            return f"{self.name} ({self.variant})"
        return self.name

class Confirmation(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="confirmation")
    status = models.CharField(
        max_length=10,
        choices=[("pending", "Pending"), ("yes", "Yes"), ("no", "No")],
        default="pending"
    )
    confirmed_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.order} - {self.status}"


class BostaCity(models.Model):
    bosta_id = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    country_code = models.CharField(max_length=10, default="EG")

    def __str__(self):
        return self.name

class BostaDistrict(models.Model):
    bosta_id = models.CharField(max_length=100, db_index=True)
    name = models.CharField(max_length=100)
    name_ar = models.CharField(max_length=100, null=True, blank=True)       
    city = models.ForeignKey(BostaCity, on_delete=models.CASCADE, related_name="districts")

    def __str__(self):
        return f"{self.name}, {self.city.name}"
    

class AramexConfiguration(models.Model):
    brand = models.OneToOneField(
        Brand, 
        on_delete=models.CASCADE, 
        related_name='aramex_configuration'
    )
    username = models.CharField(max_length=255, help_text="Aramex Account Username (Email)")
    password = models.CharField(max_length=255, help_text="Aramex Account Password")
    account_number = models.CharField(max_length=50, help_text="Aramex Account Number")
    account_pin = models.CharField(max_length=50, help_text="Aramex Account PIN")
    account_entity = models.CharField(max_length=10, help_text="Aramex Account Entity (e.g., CAI)")
    account_country_code = models.CharField(max_length=10, default="EG", help_text="Aramex Account Country Code")
    version = models.CharField(max_length=10, default="v1.0", help_text="API Version")

    def __str__(self):
        return f"Aramex Config for {self.brand.name}"
    


class AramexCity(models.Model):
    name = models.CharField(max_length=100, unique=True, db_index=True)
    # You will fill this with: Cairo, Giza, Alexandria, Dakahlia, etc.
    
    def __str__(self):
        return self.name

class AramexDistrict(models.Model):
    city = models.ForeignKey(AramexCity, on_delete=models.CASCADE, related_name="districts")
    name = models.CharField(max_length=100, db_index=True)
    # You will fill this with: Maadi, Zamalek, Nasr City (Linked to Cairo)
    
    def __str__(self):
        return f"{self.name} ({self.city.name})"  



class KhazenlyConfiguration(models.Model):
    brand = models.OneToOneField(
        Brand, 
        on_delete=models.CASCADE, 
        related_name='khazenly_configuration'
    )
    # Credentials from the Khazenly Dashboard
    client_id = models.CharField(max_length=255, help_text="Consumer Key")
    client_secret = models.CharField(max_length=255, help_text="Consumer Secret")
    store_url = models.CharField(max_length=255, help_text="e.g. FASHONSTA.com")
    
    # Connection Tokens
    access_token = models.TextField(blank=True, null=True)
    refresh_token = models.TextField(blank=True, null=True, help_text="Paste the Refresh Token you got from the handshake here.")
    token_expiry = models.DateTimeField(blank=True, null=True)
    
    # Environment Toggle
    is_live = models.BooleanField(default=False, help_text="Checked = Production, Unchecked = Testing")

    def __str__(self):
        return f"Khazenly Config for {self.brand.name}"   


# orders/models.py

# ... existing imports ...

class KhazenlyCity(models.Model):
    name = models.CharField(max_length=100, unique=True, db_index=True, help_text="The exact city name required by Khazenly API (e.g., 'Cairo', 'Giza', 'Mahalla')")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Khazenly Cities"       