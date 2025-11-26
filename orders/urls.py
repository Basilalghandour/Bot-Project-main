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


urlpatterns = router.urls + brands_router.urls + customer_router.urls
