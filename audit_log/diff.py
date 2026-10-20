"""Snapshot and diff model instances into JSON-friendly values."""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any

from django.db import models
from django.db.models.fields.files import FieldFile

from .conf import get_setting


def serialize_value(value: Any) -> Any:
    """Reduce a field value to something ``json.dumps`` accepts and humans can read."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, models.Model):
        return value.pk
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, FieldFile):
        return value.name or None
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (list, tuple, set, frozenset)):
        return [serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): serialize_value(v) for k, v in value.items()}
    return str(value)


def tracked_fields(
    model: type[models.Model], fields: set[str] | None, exclude: set[str]
) -> list[str]:
    """Concrete, non-m2m field names to track for ``model`` honouring include/exclude."""
    names: list[str] = []
    for f in model._meta.concrete_fields:
        if f.primary_key:
            continue
        if fields is not None and f.name not in fields:
            continue
        if f.name in exclude:
            continue
        names.append(f.name)
    return names


def snapshot(instance: models.Model, field_names: list[str]) -> dict[str, Any]:
    """Current values of ``field_names`` on ``instance`` (FKs by ``<name>_id`` to avoid queries)."""
    data: dict[str, Any] = {}
    for name in field_names:
        field = instance._meta.get_field(name)
        if field.is_relation and (field.many_to_one or field.one_to_one):
            data[name] = serialize_value(getattr(instance, field.attname))
        else:
            data[name] = serialize_value(getattr(instance, name))
    return data


def diff(old: dict[str, Any] | None, new: dict[str, Any] | None, mask: set[str]) -> dict[str, list]:
    """``{field: [old, new]}`` for every field whose value changed. Masked fields hide values."""
    old = old or {}
    new = new or {}
    mask_value = get_setting("MASK_VALUE")
    changes: dict[str, list] = {}
    for name in sorted(set(old) | set(new)):
        before = old.get(name)
        after = new.get(name)
        if before == after:
            continue
        if name in mask:
            changes[name] = [
                mask_value if before is not None else None,
                mask_value if after is not None else None,
            ]
        else:
            changes[name] = [before, after]
    return changes


def object_repr(instance: models.Model) -> str:
    try:
        text = str(instance)
    except Exception:  # pragma: no cover - defensive against odd __str__ implementations
        text = f"{instance._meta.label} {instance.pk}"
    limit = get_setting("MAX_REPR_LENGTH")
    return text if len(text) <= limit else text[: limit - 1] + "…"
