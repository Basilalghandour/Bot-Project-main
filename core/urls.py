from django.contrib import admin
from django.urls import path, include
from orders import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.landing_page, name='home'),  # <--- Add this line for the landing page
    path('login/', views.login_page, name='login'),   # <--- Added
    path('signup/', views.signup_page, name='signup'), # <--- Added
    path('api/', include('orders.urls')),  # import all API routes from orders app
    path('webhooks/whatsapp/', views.whatsapp_webhook, name='whatsapp-webhook'),
]
