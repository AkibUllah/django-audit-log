from __future__ import annotations

import json

from django.contrib import admin
from django.utils.html import format_html, format_html_join

from .models import AuditEntry


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    """Read-only browser for the audit trail."""

    list_display = (
        "timestamp",
        "action",
        "model_label",
        "object_pk",
        "object_repr",
        "actor_repr",
        "ip",
    )
    list_filter = ("action", "content_type", "timestamp")
    search_fields = ("object_pk", "object_repr", "actor_repr", "request_id", "ip")
    date_hierarchy = "timestamp"
    ordering = ("-timestamp",)
    list_select_related = ("content_type", "actor")
    readonly_fields = (
        "timestamp",
        "action",
        "content_type",
        "object_pk",
        "object_repr",
        "actor",
        "actor_repr",
        "ip",
        "user_agent",
        "request_id",
        "changes_table",
        "extra_pretty",
    )
    fields = readonly_fields

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="Model", ordering="content_type__model")
    def model_label(self, obj: AuditEntry) -> str:
        return obj.model_label

    @admin.display(description="Changes")
    def changes_table(self, obj: AuditEntry):
        if not obj.changes:
            return "-"
        rows = []
        for name, value in sorted(obj.changes.items()):
            if isinstance(value, list) and len(value) == 2:
                before, after = value
            else:
                before, after = "", json.dumps(value, default=str)
            rows.append((name, json.dumps(before, default=str), json.dumps(after, default=str)))
        body = format_html_join(
            "", "<tr><th>{}</th><td><code>{}</code></td><td><code>{}</code></td></tr>", rows
        )
        return format_html(
            "<table><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead>"
            "<tbody>{}</tbody></table>",
            body,
        )

    @admin.display(description="Extra")
    def extra_pretty(self, obj: AuditEntry):
        return format_html("<pre>{}</pre>", json.dumps(obj.extra, indent=2, default=str))
