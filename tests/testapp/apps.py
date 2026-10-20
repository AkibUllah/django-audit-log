from django.apps import AppConfig


class TestAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tests.testapp"
    label = "testapp"

    def ready(self):
        import audit_log

        from .models import Author, Book, Customer

        audit_log.register(Author)
        audit_log.register(Book, exclude=["updated_at"])
        audit_log.register(
            Customer,
            mask=["nid_number", "phone"],
            fields=["name", "nid_number", "phone", "balance"],
        )
