from django.contrib import admin
from django.urls import path, include
from orders import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('orders.urls')),  # import all API routes from orders app
    path('webhooks/whatsapp/', views.whatsapp_webhook, name='whatsapp-webhook'),
]
