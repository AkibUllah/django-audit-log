from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class AuditEntryQuerySet(models.QuerySet):
    def for_object(self, instance: models.Model) -> AuditEntryQuerySet:
        return self.filter(
            content_type=ContentType.objects.get_for_model(instance.__class__),
            object_pk=str(instance.pk),
        )

    def for_model(self, model: type[models.Model]) -> AuditEntryQuerySet:
        return self.filter(content_type=ContentType.objects.get_for_model(model))

    def by_actor(self, actor) -> AuditEntryQuerySet:
        return self.filter(actor=actor)

    def older_than(self, moment) -> AuditEntryQuerySet:
        return self.filter(timestamp__lt=moment)


class AuditEntry(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        M2M_ADD = "m2m_add", "M2M add"
        M2M_REMOVE = "m2m_remove", "M2M remove"
        M2M_CLEAR = "m2m_clear", "M2M clear"
        BULK_UPDATE = "bulk_update", "Bulk update"
        BULK_DELETE = "bulk_delete", "Bulk delete"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    actor_repr = models.CharField(max_length=200, blank=True, db_index=True)
    action = models.CharField(max_length=12, choices=Action.choices, db_index=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_pk = models.CharField(max_length=255)
    object_repr = models.CharField(max_length=200, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    extra = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    objects = AuditEntryQuerySet.as_manager()

    class Meta:
        ordering = ("-timestamp", "-id")
        verbose_name = "audit entry"
        verbose_name_plural = "audit entries"
        indexes = [models.Index(fields=["content_type", "object_pk"], name="audit_ct_pk_idx")]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.content_type.model} {self.object_pk}"

    @property
    def model_label(self) -> str:
        return f"{self.content_type.app_label}.{self.content_type.model}"

    @property
    def changed_fields(self) -> list[str]:
        return sorted(self.changes.keys())
