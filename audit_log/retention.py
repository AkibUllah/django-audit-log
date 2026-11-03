"""Retention classes: how long audit entries are kept, per action and per model.

Configured under ``AUDIT_LOG["RETENTION"]`` in days; ``None`` means keep forever::

    AUDIT_LOG = {
        "RETENTION": {
            "default": 365,          # every action without its own rule
            "update": 180,
            "delete": 3650,
            "bulk_delete": None,     # keep forever
            "models": {              # optional per-model overrides (app_label.model)
                "shop.cart": {"default": 30},
                "shop.customer": {"update": 730},
            },
        }
    }

The most specific rule wins: model + action, then the model's ``default``, then the
action, then the global ``default``. Without a global ``default`` anything not matched
by a rule is kept forever, so an incomplete policy never deletes more than it names.
"""

from __future__ import annotations

import operator
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import reduce
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from .conf import get_setting
from .models import AuditEntry

DEFAULT = "default"
MODELS = "models"
ACTIONS: tuple[str, ...] = tuple(AuditEntry.Action.values)

_MODEL_LABEL = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")
_UNSET: Any = object()


@dataclass(frozen=True)
class ModelRetention:
    """Overrides for one model; ``default`` is ``_UNSET`` when the model has none."""

    default: int | None = _UNSET
    actions: dict[str, int | None] = field(default_factory=dict)

    @property
    def has_default(self) -> bool:
        return self.default is not _UNSET


@dataclass(frozen=True)
class RetentionClass:
    """One rule of the policy and the entries it governs.

    ``name`` is ``"default"``, an action (``"delete"``), a model label (``"shop.cart"``,
    that model's default) or both (``"shop.customer:update"``). ``filter`` selects the
    entries the rule applies to regardless of their age.
    """

    name: str
    days: int | None
    filter: Q
    model: str | None = None

    def cutoff(self, now: datetime) -> datetime | None:
        """Entries strictly older than this are expired; ``None`` when kept forever."""
        return None if self.days is None else now - timedelta(days=self.days)


def _any(parts: list[Q]) -> Q | None:
    return reduce(operator.or_, parts) if parts else None


def _excluding(condition: Q | None) -> Q:
    return ~condition if condition is not None else Q()


@dataclass(frozen=True)
class RetentionPolicy:
    default: int | None = None
    actions: dict[str, int | None] = field(default_factory=dict)
    models: dict[str, ModelRetention] = field(default_factory=dict)

    def days_for(self, model_label: str, action: str) -> int | None:
        """Retention in days for an entry of ``model_label`` / ``action`` (``None`` = forever)."""
        override = self.models.get(model_label.lower())
        if override is not None:
            if action in override.actions:
                return override.actions[action]
            if override.has_default:
                return override.default
        return self.actions.get(action, self.default)

    def classes(self) -> list[RetentionClass]:
        """The policy as disjoint classes; every entry belongs to exactly one of them."""
        classes: list[RetentionClass] = []
        claimed: list[Q] = []  # entries already governed by a per-model rule
        for label, override in sorted(self.models.items()):
            app_label, model_name = label.split(".")
            of_model = Q(content_type__app_label=app_label, content_type__model=model_name)
            for action in ACTIONS:
                if action in override.actions:
                    classes.append(
                        RetentionClass(
                            f"{label}:{action}",
                            override.actions[action],
                            of_model & Q(action=action),
                            label,
                        )
                    )
            if override.has_default:
                rest = of_model & _excluding(_any([Q(action=a) for a in override.actions]))
                classes.append(RetentionClass(label, override.default, rest, label))
                claimed.append(of_model)
            else:
                claimed.append(of_model & Q(action__in=list(override.actions)))

        unclaimed = _excluding(_any(claimed))
        for action in ACTIONS:
            if action in self.actions:
                classes.append(
                    RetentionClass(action, self.actions[action], unclaimed & Q(action=action))
                )
        other_actions = _excluding(_any([Q(action=a) for a in self.actions]))
        classes.append(RetentionClass(DEFAULT, self.default, unclaimed & other_actions))
        return classes

    def expired_filter(self, now: datetime) -> Q | None:
        """A filter for entries past their retention at ``now``; ``None`` if none can expire."""
        return _any(
            [
                cls.filter & Q(timestamp__lt=cutoff)
                for cls in self.classes()
                if (cutoff := cls.cutoff(now)) is not None
            ]
        )


def _days(value: Any, where: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ImproperlyConfigured(
            f"AUDIT_LOG['RETENTION']{where} must be a whole number of days or None "
            f"(keep forever), got {value!r}."
        )
    if value < 0:
        raise ImproperlyConfigured(f"AUDIT_LOG['RETENTION']{where} must be >= 0, got {value}.")
    return value


def _rules(raw: dict, where: str, allowed: tuple[str, ...]) -> dict[str, int | None]:
    rules: dict[str, int | None] = {}
    for key, value in raw.items():
        if key not in allowed:
            raise ImproperlyConfigured(
                f"AUDIT_LOG['RETENTION']{where} has an unknown key {key!r}; "
                f"expected one of: {', '.join(allowed)}."
            )
        rules[key] = _days(value, f"{where}[{key!r}]")
    return rules


def parse_policy(raw: Any) -> RetentionPolicy | None:
    """Validate the ``RETENTION`` setting; raises ``ImproperlyConfigured`` with the bad key."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ImproperlyConfigured(
            f"AUDIT_LOG['RETENTION'] must be a dict of action -> days, got {type(raw).__name__}."
        )
    raw = dict(raw)
    raw_models = raw.pop(MODELS, {})
    rules = _rules(raw, "", (DEFAULT, *ACTIONS, MODELS))
    default = rules.pop(DEFAULT, None)

    if not isinstance(raw_models, dict):
        raise ImproperlyConfigured(
            "AUDIT_LOG['RETENTION']['models'] must be a dict of 'app_label.model' -> rules."
        )
    models: dict[str, ModelRetention] = {}
    for label, model_raw in raw_models.items():
        where = f"['models'][{label!r}]"
        if not isinstance(label, str) or not _MODEL_LABEL.match(label.lower()):
            raise ImproperlyConfigured(
                f"AUDIT_LOG['RETENTION']['models'] key {label!r} must look like 'app_label.model'."
            )
        if not isinstance(model_raw, dict) or not model_raw:
            raise ImproperlyConfigured(
                f"AUDIT_LOG['RETENTION']{where} must be a non-empty dict of action -> days."
            )
        if label.lower() in models:
            raise ImproperlyConfigured(
                f"AUDIT_LOG['RETENTION']['models'] lists {label.lower()!r} more than once."
            )
        model_rules = _rules(model_raw, where, (DEFAULT, *ACTIONS))
        model_default = model_rules.pop(DEFAULT, _UNSET)
        models[label.lower()] = ModelRetention(default=model_default, actions=model_rules)

    return RetentionPolicy(default=default, actions=rules, models=models)


def get_policy() -> RetentionPolicy | None:
    """The configured policy, or ``None`` when ``AUDIT_LOG["RETENTION"]`` is not set."""
    return parse_policy(get_setting("RETENTION"))
