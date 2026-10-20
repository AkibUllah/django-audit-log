"""django-audit-log: field-level audit trails for Django models.

Typical use::

    # myapp/apps.py
    from django.apps import AppConfig

    class MyAppConfig(AppConfig):
        name = "myapp"

        def ready(self):
            import audit_log
            from .models import Customer, Order

            audit_log.register(Order, exclude=["updated_at"])
            audit_log.register(Customer, mask=["nid_number", "phone"])
"""

from .context import audit_context, disable_auditing, get_context, set_actor
from .registry import audited, is_registered, register, registry, unregister

__version__ = "0.1.0"

#: Registry singleton, so ``from audit_log import audit; audit.register(Model)`` also reads well.
audit = registry

__all__ = [
    "__version__",
    "audit",
    "audit_context",
    "audited",
    "disable_auditing",
    "get_context",
    "is_registered",
    "register",
    "registry",
    "set_actor",
    "unregister",
]
