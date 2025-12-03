from django.contrib import admin
from django.urls import path, include
from orders import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.landing_page, name='home'),
    path('login/', views.login_page, name='login'),
    path('signup/', views.signup_page, name='signup'),
    
    # --- NEW VALIDATION URL ---
    path('validate-step1/', views.validate_step1, name='validate_step1'),
    
    path('api/', include('orders.urls')),
    path('webhooks/whatsapp/', views.whatsapp_webhook, name='whatsapp-webhook'),
]