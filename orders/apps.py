# in orders/apps.py

from django.apps import AppConfig

class OrdersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'orders'

    # --- THIS METHOD WAS MISSING ---
    def ready(self):
        """
        This method is called when the app is ready, and it's where
        we import our signals to connect them.
        """
        import orders.signals