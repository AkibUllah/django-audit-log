"""Populate the audit context from the incoming request.

Add ``"audit_log.middleware.AuditMiddleware"`` *after*
``AuthenticationMiddleware`` so ``request.user`` is resolved. The request id is taken
from the configured header (default ``X-Request-ID``) or generated, and echoed back on
the response so clients and log aggregators can correlate.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .conf import get_setting
from .context import AuditContext, _repr_actor, reset_context, set_context


def client_ip(request: HttpRequest) -> str | None:
    if get_setting("TRUST_X_FORWARDED_FOR"):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def request_id_for(request: HttpRequest) -> str:
    header = "HTTP_" + get_setting("REQUEST_ID_HEADER").upper().replace("-", "_")
    return (request.META.get(header) or uuid.uuid4().hex)[:64]


class AuditMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        actor = user if (user is not None and getattr(user, "is_authenticated", False)) else None
        request_id = request_id_for(request)
        token = set_context(
            AuditContext(
                actor=actor,
                actor_repr=_repr_actor(actor),
                ip=client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
                request_id=request_id,
                extra={"path": request.path, "method": request.method},
            )
        )
        request.audit_request_id = request_id
        try:
            response = self.get_response(request)
        finally:
            reset_context(token)
        response[get_setting("REQUEST_ID_HEADER")] = request_id
        return response
