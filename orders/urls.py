from rest_framework_nested import routers
from .views import BrandViewSet, OrderViewSet, ConfirmationViewSet
from django.urls import path
from . import views

router = routers.DefaultRouter()
router.register('brands', BrandViewSet, basename="brand")
router.register('orders', OrderViewSet, basename="order")
router.register('confirmations', ConfirmationViewSet, basename="confirmation")
router.register('customers', views.CustomerOrderViewSet, basename="customer")
# Nested router for orders under brands
brands_router = routers.NestedDefaultRouter(router, 'brands', lookup='brand')
brands_router.register('orders', OrderViewSet, basename='brand-orders')
brands_router.register('dashboard', views.DashboardViewSet, basename='brand-dashboard')

customer_router = routers.NestedDefaultRouter(router, 'customers', lookup='customer')
customer_router.register('orders', views.CustomerOrderViewSet, basename='customer-orders')


urlpatterns =[
    path('change-password/', views.change_password, name='change_password'),
    path('update-profile/', views.update_profile, name='update_profile'),
    path('api/send-otp/', views.send_otp_view, name='send_otp'),
    path('api/verify-otp/', views.verify_otp_view, name='verify_otp'),
    path('', views.landing_page, name='home'),
    path('api/send-change-phone-otp/', views.send_change_phone_otp, name='send_change_phone_otp'),
    path('api/verify-change-phone/', views.verify_change_phone_otp, name='verify_change_phone_otp'),
    path('api/send-change-phone-otp/', views.send_change_phone_otp, name='send_change_phone_otp'),
    path('api/verify-change-phone/', views.verify_change_phone_otp, name='verify_change_phone_otp'),
    path('login/', views.login_page, name='login'),
    path('signup/', views.signup_page, name='signup'), # <--- Add this line
] + router.urls + brands_router.urls + customer_router.urls
