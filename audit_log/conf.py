"""Library settings, read from ``settings.AUDIT_LOG`` with defaults.

::

    AUDIT_LOG = {
        "MASK_VALUE": "***",
        "REQUEST_ID_HEADER": "X-Request-ID",
        "TRUST_X_FORWARDED_FOR": True,
        "STORE_UNCHANGED_UPDATES": False,
        "MAX_REPR_LENGTH": 200,
    }
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

DEFAULTS: dict[str, Any] = {
    "MASK_VALUE": "***",
    "REQUEST_ID_HEADER": "X-Request-ID",
    "TRUST_X_FORWARDED_FOR": True,
    "STORE_UNCHANGED_UPDATES": False,
    "MAX_REPR_LENGTH": 200,
}


def get_setting(name: str) -> Any:
    overrides = getattr(settings, "AUDIT_LOG", {}) or {}
    return overrides.get(name, DEFAULTS[name])
