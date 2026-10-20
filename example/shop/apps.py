from django.apps import AppConfig


class ShopConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shop"

    def ready(self):
        import audit_log

        from .models import Customer, Order, Product

        audit_log.register(Product, exclude=["updated_at"])
        audit_log.register(Customer, mask=["nid_number", "phone"])
        audit_log.register(Order, exclude=["updated_at"])
