"""Model registration.

``register(Model, fields=None, exclude=(), mask=(), m2m=True)`` connects the signal
receivers for that model and remembers which fields to track and which to mask.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from django.db import models
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save

from .diff import tracked_fields


class AlreadyRegistered(Exception):
    pass


class NotRegistered(Exception):
    pass


@dataclass(frozen=True)
class ModelConfig:
    model: type[models.Model]
    fields: tuple[str, ...]
    mask: frozenset[str] = frozenset()
    m2m_fields: tuple[str, ...] = ()
    extra: dict = field(default_factory=dict)

    @property
    def field_list(self) -> list[str]:
        return list(self.fields)


class Registry:
    def __init__(self) -> None:
        self._configs: dict[type[models.Model], ModelConfig] = {}
        self._m2m_through: dict[type[models.Model], tuple[type[models.Model], str]] = {}

    # -- registration -------------------------------------------------------
    def register(
        self,
        model: type[models.Model],
        *,
        fields: Iterable[str] | None = None,
        exclude: Iterable[str] = (),
        mask: Iterable[str] = (),
        m2m: bool = True,
        **extra,
    ) -> type[models.Model]:
        if model in self._configs:
            raise AlreadyRegistered(f"{model._meta.label} is already registered for auditing.")
        if model._meta.abstract:
            raise ValueError("Abstract models cannot be audited; register the concrete subclasses.")

        field_set = set(fields) if fields is not None else None
        exclude_set = set(exclude)
        self._validate_names(model, (field_set or set()) | exclude_set | set(mask))
        names = tracked_fields(model, field_set, exclude_set)
        m2m_names = tuple(
            f.name
            for f in model._meta.many_to_many
            if m2m and f.name not in exclude_set and (field_set is None or f.name in field_set)
        )
        config = ModelConfig(
            model=model,
            fields=tuple(names),
            mask=frozenset(mask),
            m2m_fields=m2m_names,
            extra=dict(extra),
        )
        self._configs[model] = config
        self._connect(model, config)
        return model

    def unregister(self, model: type[models.Model]) -> None:
        config = self._configs.pop(model, None)
        if config is None:
            raise NotRegistered(f"{model._meta.label} is not registered for auditing.")
        self._disconnect(model, config)

    def is_registered(self, model: type[models.Model]) -> bool:
        return model in self._configs

    def get_config(self, model: type[models.Model]) -> ModelConfig:
        try:
            return self._configs[model]
        except KeyError:
            raise NotRegistered(f"{model._meta.label} is not registered for auditing.")

    def registered_models(self) -> list[type[models.Model]]:
        return list(self._configs)

    def through_owner(self, through: type[models.Model]) -> tuple[type[models.Model], str] | None:
        return self._m2m_through.get(through)

    # -- internals -------------------------------------------------------------
    @staticmethod
    def _validate_names(model: type[models.Model], names: set[str]) -> None:
        known = {f.name for f in model._meta.get_fields()}
        unknown = sorted(n for n in names if n not in known)
        if unknown:
            raise ValueError(f"{model._meta.label} has no field(s) {', '.join(unknown)}.")

    def _connect(self, model: type[models.Model], config: ModelConfig) -> None:
        from . import signals

        uid = f"audit_log.{model._meta.label_lower}"
        pre_save.connect(signals.on_pre_save, sender=model, dispatch_uid=f"{uid}.pre_save")
        post_save.connect(signals.on_post_save, sender=model, dispatch_uid=f"{uid}.post_save")
        post_delete.connect(signals.on_post_delete, sender=model, dispatch_uid=f"{uid}.post_delete")
        for name in config.m2m_fields:
            through = model._meta.get_field(name).remote_field.through
            self._m2m_through[through] = (model, name)
            m2m_changed.connect(
                signals.on_m2m_changed, sender=through, dispatch_uid=f"{uid}.m2m.{name}"
            )

    def _disconnect(self, model: type[models.Model], config: ModelConfig) -> None:
        from . import signals

        uid = f"audit_log.{model._meta.label_lower}"
        pre_save.disconnect(signals.on_pre_save, sender=model, dispatch_uid=f"{uid}.pre_save")
        post_save.disconnect(signals.on_post_save, sender=model, dispatch_uid=f"{uid}.post_save")
        post_delete.disconnect(
            signals.on_post_delete, sender=model, dispatch_uid=f"{uid}.post_delete"
        )
        for name in config.m2m_fields:
            through = model._meta.get_field(name).remote_field.through
            self._m2m_through.pop(through, None)
            m2m_changed.disconnect(
                signals.on_m2m_changed, sender=through, dispatch_uid=f"{uid}.m2m.{name}"
            )


registry = Registry()
register = registry.register
unregister = registry.unregister
is_registered = registry.is_registered


def audited(
    _model: type[models.Model] | None = None, **options
) -> Callable[[type[models.Model]], type[models.Model]] | type[models.Model]:
    """Class decorator: ``@audited`` or ``@audited(exclude=["updated_at"], mask=["phone"])``."""

    def decorator(model: type[models.Model]) -> type[models.Model]:
        registry.register(model, **options)
        return model

    return decorator(_model) if _model is not None else decorator
