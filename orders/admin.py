from django.contrib import admin
from .models import Brand, Order, Confirmation, OrderItem

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'website', 'contact_email', 'phone_number', 'created_at')
    search_fields = ('name', 'website', 'contact_email', 'phone_number')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'brand', 'get_customer_name', 'get_customer_phone', 'created_at')
    list_filter = ('brand',)
    search_fields = ('items__product_name', 'customer__first_name', 'customer__last_name', 'customer__phone_number')

    def get_customer_name(self, obj):
        if obj.customer:
            return f"{obj.customer.first_name} {obj.customer.last_name}"
        return "-"
    get_customer_name.short_description = "Customer Name"

    def get_customer_phone(self, obj):
        if obj.customer:
            return obj.customer.phone_number
        return "-"
    get_customer_phone.short_description = "Customer Phone"


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "product_name", "quantity", "price")
    list_filter = ("product_name", "order__created_at")
    search_fields = ("product_name", "order__customer__first_name", "order__customer__last_name", "order__customer__phone_number")    


@admin.register(Confirmation)
class ConfirmationAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'status', 'confirmed_at')
    list_filter = ('status',)
    search_fields = ('order__items__product_name', 'order__customer__first_name', 'order__customer__last_name')
