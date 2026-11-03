"""System checks for the ``AUDIT_LOG`` settings."""

from __future__ import annotations

from django.apps import apps
from django.core.checks import Tags, Warning, register

from .retention import get_policy


@register(Tags.models)
def check_retention_models(app_configs=None, **kwargs) -> list[Warning]:
    """Warn about per-model retention rules naming a model that is not installed.

    Only a warning: entries of a model that was removed stay in the table, and a rule
    for them is still meaningful.
    """
    policy = get_policy()
    if policy is None:
        return []
    warnings = []
    for label in policy.models:
        try:
            apps.get_model(label)
        except LookupError:
            warnings.append(
                Warning(
                    f"AUDIT_LOG['RETENTION']['models'] has a rule for {label!r}, "
                    "which is not an installed model.",
                    hint="Check the spelling (app_label.model_name) or remove the rule.",
                    id="audit_log.W001",
                )
            )
    return warnings
