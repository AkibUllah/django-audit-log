"""Audited equivalents of queryset operations that bypass model signals.

``QuerySet.update()`` and ``QuerySet.delete()`` on large sets never call ``save()`` /
``post_delete`` per row (delete does fire signals, but one SQL-level update does not),
so these helpers compute the per-object diff first and then write one entry per
affected object with a shared ``batch_id`` in ``extra``.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db import models, transaction

from .diff import diff, serialize_value, snapshot
from .registry import registry
from .signals import write_entry


@transaction.atomic
def bulk_update_audited(queryset: models.QuerySet, **values: Any) -> int:
    """``queryset.update(**values)`` plus one ``bulk_update`` entry per changed row."""
    model = queryset.model
    config = registry.get_config(model)
    batch_id = uuid.uuid4().hex
    before = {obj.pk: (obj, snapshot(obj, config.field_list)) for obj in queryset}
    updated = queryset.model._default_manager.filter(pk__in=list(before)).update(**values)
    new_values = {k: serialize_value(v) for k, v in values.items()}
    for obj, old in before.values():
        new = {**old, **{k: v for k, v in new_values.items() if k in old}}
        changes = diff(old, new, config.mask)
        if changes:
            for name, value in values.items():
                setattr(obj, name, value)
            write_entry(obj, "bulk_update", changes, extra={"batch_id": batch_id})
    return updated


@transaction.atomic
def bulk_delete_audited(queryset: models.QuerySet) -> int:
    """Delete with one ``bulk_delete`` entry per row (signals for the model are suppressed)."""
    from .context import disable_auditing

    model = queryset.model
    config = registry.get_config(model)
    batch_id = uuid.uuid4().hex
    objects = list(queryset)
    for obj in objects:
        write_entry(
            obj,
            "bulk_delete",
            diff(snapshot(obj, config.field_list), None, config.mask),
            extra={"batch_id": batch_id},
        )
    with disable_auditing():
        deleted, _ = model._default_manager.filter(pk__in=[o.pk for o in objects]).delete()
    return deleted
