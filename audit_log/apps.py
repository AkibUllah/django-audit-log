from django.apps import AppConfig


class AuditLogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "audit_log"
    verbose_name = "Audit log"

    def ready(self):
        from . import checks  # noqa: F401  (registers the system checks)
        from .retention import get_policy

        # Fail at startup, not at the first prune, when the retention setting is invalid.
        get_policy()
