from rest_framework import serializers
from .models import Brand, Order, OrderItem, Customer, Confirmation
from decimal import Decimal

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["product_name", "quantity", "price", "size"]

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, write_only=True)
    
    # Accept shipping_cost and total_cost during creation
    shipping_cost = serializers.DecimalField(max_digits=10, decimal_places=2, write_only=True)
    total_cost = serializers.DecimalField(max_digits=10, decimal_places=2, write_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "external_id", "customer", "created_at", "status", 
            "responded_at", "items", "shipping_cost", "total_cost"
        ]
        # We can now make total_cost readable, as it's a stored field
        read_only_fields = ["id", "customer"] 

    def create(self, validated_data):
        # Pop the nested and write-only data
        items_data = validated_data.pop('items')
        shipping_cost = validated_data.pop('shipping_cost', Decimal("0.00"))
        total_cost = validated_data.pop('total_cost', Decimal("0.00"))
        
        customer = self.context.get('customer')

        # --- SIMPLIFIED: No manual calculation needed ---
        # Create the Order instance with the pre-calculated total
        order = Order.objects.create(
            customer=customer,
            shipping_cost=shipping_cost,
            total_cost=total_cost,
            **validated_data
        )

        # Create the associated OrderItem instances
        for item_data in items_data:
            OrderItem.objects.create(order=order, **item_data)
            
        return order

class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = '__all__'
        read_only_fields = ['webhook_id']

class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = '__all__'

class ConfirmationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Confirmation
        fields = '__all__'