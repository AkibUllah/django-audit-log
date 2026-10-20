"""Per-request / per-task audit context.

The middleware fills this from the HTTP request; management commands, Celery tasks
or scripts use ``audit_context(actor=...)`` so entries still carry a responsible
actor. ``contextvars`` makes it safe under threads and asyncio alike.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class AuditContext:
    actor: Any = None  # a user instance, or None
    actor_repr: str = ""
    ip: str | None = None
    user_agent: str = ""
    request_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


_DEFAULT_CONTEXT = AuditContext()
_context: contextvars.ContextVar[AuditContext] = contextvars.ContextVar("audit_log_context")


def get_context() -> AuditContext:
    return _context.get(_DEFAULT_CONTEXT)


def set_context(ctx: AuditContext) -> contextvars.Token:
    return _context.set(ctx)


def reset_context(token: contextvars.Token) -> None:
    _context.reset(token)


def set_actor(actor: Any, actor_repr: str = "") -> None:
    """Set the actor for the rest of the current context (e.g. inside a command)."""
    current = get_context()
    _context.set(replace(current, actor=actor, actor_repr=actor_repr or _repr_actor(actor)))


def _repr_actor(actor: Any) -> str:
    if actor is None:
        return ""
    for attr in ("get_username", "username", "email"):
        value = getattr(actor, attr, None)
        if callable(value):
            value = value()
        if value:
            return str(value)
    return str(actor)


@contextmanager
def audit_context(
    actor: Any = None,
    *,
    actor_repr: str = "",
    ip: str | None = None,
    user_agent: str = "",
    request_id: str = "",
    **extra: Any,
) -> Iterator[AuditContext]:
    """Temporarily set the audit context (actor, request id, ...) for a block of code."""
    current = get_context()
    ctx = AuditContext(
        actor=actor if actor is not None else current.actor,
        actor_repr=actor_repr or (_repr_actor(actor) if actor is not None else current.actor_repr),
        ip=ip if ip is not None else current.ip,
        user_agent=user_agent or current.user_agent,
        request_id=request_id or current.request_id,
        extra={**current.extra, **extra},
        enabled=current.enabled,
    )
    token = set_context(ctx)
    try:
        yield ctx
    finally:
        reset_context(token)


@contextmanager
def disable_auditing() -> Iterator[None]:
    """Suppress audit entries inside the block (data migrations, bulk imports, fixtures)."""
    token = set_context(replace(get_context(), enabled=False))
    try:
        yield
    finally:
        reset_context(token)
