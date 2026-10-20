"""Optional Django REST Framework integration.

::

    from audit_log.drf import AuditEntryViewSet
    router.register("audit", AuditEntryViewSet, basename="audit")

Requires ``pip install django-audit-log[drf]``.
"""

from __future__ import annotations

try:
    from rest_framework import pagination, permissions, serializers, viewsets
except ImportError as exc:  # pragma: no cover
    raise ImportError("audit_log.drf requires djangorestframework") from exc

from .models import AuditEntry


class AuditEntrySerializer(serializers.ModelSerializer):
    model = serializers.CharField(source="model_label", read_only=True)

    class Meta:
        model = AuditEntry
        fields = (
            "id",
            "timestamp",
            "action",
            "model",
            "object_pk",
            "object_repr",
            "actor",
            "actor_repr",
            "changes",
            "ip",
            "user_agent",
            "request_id",
            "extra",
        )
        read_only_fields = fields


class AuditEntryPagination(pagination.PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


class AuditEntryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only listing with ``?model=app.model``, ``?object_pk=``, ``?action=``, ``?actor=``."""

    serializer_class = AuditEntrySerializer
    permission_classes = (permissions.IsAdminUser,)
    pagination_class = AuditEntryPagination
    queryset = AuditEntry.objects.select_related("content_type", "actor")

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if model := params.get("model"):
            app_label, _, model_name = model.lower().partition(".")
            qs = qs.filter(content_type__app_label=app_label, content_type__model=model_name)
        if object_pk := params.get("object_pk"):
            qs = qs.filter(object_pk=object_pk)
        if action := params.get("action"):
            qs = qs.filter(action=action)
        if actor := params.get("actor"):
            qs = qs.filter(actor_id=actor)
        if request_id := params.get("request_id"):
            qs = qs.filter(request_id=request_id)
        return qs
