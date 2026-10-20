"""Signal receivers that turn model events into ``AuditEntry`` rows."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models

from .conf import get_setting
from .context import get_context
from .diff import diff, object_repr, serialize_value, snapshot
from .registry import registry

logger = logging.getLogger(__name__)

_OLD_ATTR = "_audit_log_snapshot"


def write_entry(
    instance: models.Model,
    action: str,
    changes: dict[str, Any] | None = None,
    *,
    extra: dict[str, Any] | None = None,
):
    """Create an ``AuditEntry`` for ``instance`` using the current context. Returns it or None."""
    from .models import AuditEntry

    ctx = get_context()
    if not ctx.enabled:
        return None
    actor = ctx.actor if getattr(ctx.actor, "pk", None) is not None else None
    merged_extra = {**ctx.extra, **(extra or {})}
    return AuditEntry.objects.create(
        actor=actor,
        actor_repr=ctx.actor_repr,
        action=action,
        content_type=ContentType.objects.get_for_model(instance.__class__),
        object_pk=str(instance.pk),
        object_repr=object_repr(instance),
        changes=changes or {},
        ip=ctx.ip,
        user_agent=ctx.user_agent[:500],
        request_id=ctx.request_id[:64],
        extra=merged_extra,
    )


def on_pre_save(sender, instance, raw=False, **kwargs) -> None:
    if raw or not get_context().enabled:
        return
    config = registry.get_config(sender)
    if instance._state.adding or instance.pk is None:
        setattr(instance, _OLD_ATTR, None)
        return
    try:
        current = sender._default_manager.get(pk=instance.pk)
    except sender.DoesNotExist:
        setattr(instance, _OLD_ATTR, None)
        return
    setattr(instance, _OLD_ATTR, snapshot(current, config.field_list))


def on_post_save(sender, instance, created, raw=False, **kwargs) -> None:
    if raw or not get_context().enabled:
        return
    config = registry.get_config(sender)
    new = snapshot(instance, config.field_list)
    if created:
        write_entry(instance, "create", diff(None, new, config.mask))
        return
    old = getattr(instance, _OLD_ATTR, None)
    if hasattr(instance, _OLD_ATTR):
        delattr(instance, _OLD_ATTR)
    changes = diff(old, new, config.mask)
    if not changes and not get_setting("STORE_UNCHANGED_UPDATES"):
        return
    write_entry(instance, "update", changes)


def on_post_delete(sender, instance, **kwargs) -> None:
    if not get_context().enabled:
        return
    config = registry.get_config(sender)
    old = snapshot(instance, config.field_list)
    write_entry(instance, "delete", diff(old, None, config.mask))


def on_m2m_changed(sender, instance, action, reverse, model, pk_set, **kwargs) -> None:
    if not get_context().enabled or action not in {"post_add", "post_remove", "post_clear"}:
        return
    owner = registry.through_owner(sender)
    if owner is None:
        return
    owner_model, field_name = owner
    if reverse or not isinstance(instance, owner_model):
        # Changes made from the related side (tag.books.add(book)) are not attributed to
        # the audited model; tracking them would require one entry per affected owner.
        return
    audit_action = {"post_add": "m2m_add", "post_remove": "m2m_remove", "post_clear": "m2m_clear"}[
        action
    ]
    config = registry.get_config(owner_model)
    masked = field_name in config.mask
    pks = sorted(serialize_value(pk) for pk in (pk_set or set()))
    if action != "post_clear" and not pks:
        return  # add()/remove() of objects already in/absent from the relation: nothing changed
    changes = {
        field_name: {
            "action": audit_action.removeprefix("m2m_"),
            "objects": [get_setting("MASK_VALUE")] * len(pks) if masked else pks,
            "related_model": model._meta.label_lower,
        }
    }
    write_entry(instance, audit_action, changes)
