from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.admin.sites import site
from django.core.management import CommandError, call_command
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from audit_log.admin import AuditEntryAdmin
from audit_log.bulk import bulk_delete_audited, bulk_update_audited
from audit_log.models import AuditEntry
from tests.testapp.models import Author, Book

pytestmark = pytest.mark.django_db


# --- bulk helpers ------------------------------------------------------------
def test_bulk_update_audited_writes_one_entry_per_changed_row(author):
    books = [
        Book.objects.create(title=f"Vol {i}", author=author, price=Decimal("100")) for i in range(3)
    ]
    books[2].in_print = False
    books[2].save()
    AuditEntry.objects.all().delete()

    updated = bulk_update_audited(Book.objects.all(), in_print=False, price=Decimal("90.00"))
    assert updated == 3
    entries = AuditEntry.objects.filter(action="bulk_update").order_by("object_pk")
    assert entries.count() == 3
    first = entries.get(object_pk=str(books[0].pk))
    assert first.changes == {"in_print": [True, False], "price": ["100.00", "90.00"]}
    third = entries.get(object_pk=str(books[2].pk))
    assert third.changes == {"price": ["100.00", "90.00"]}  # in_print was already False
    assert len({e.extra["batch_id"] for e in entries}) == 1
    assert Book.objects.filter(in_print=False, price=Decimal("90.00")).count() == 3


def test_bulk_delete_audited(author):
    for i in range(2):
        Book.objects.create(title=f"Gone {i}", author=author)
    AuditEntry.objects.all().delete()
    deleted = bulk_delete_audited(Book.objects.filter(title__startswith="Gone"))
    assert deleted == 2
    assert Book.objects.count() == 0
    assert AuditEntry.objects.filter(action="bulk_delete").count() == 2
    assert AuditEntry.objects.filter(action="delete").count() == 0  # per-row signal suppressed


# --- prune command -----------------------------------------------------------
def _aged(entry, days):
    AuditEntry.objects.filter(pk=entry.pk).update(timestamp=timezone.now() - timedelta(days=days))


def test_audit_prune_by_days_with_dry_run_and_model_filter(author, book):
    author_entry = AuditEntry.objects.for_object(author).get()
    book_entry = AuditEntry.objects.for_object(book).get()
    _aged(author_entry, 400)
    _aged(book_entry, 400)
    recent = AuditEntry.objects.create(
        action="update", content_type=book_entry.content_type, object_pk="999", changes={}
    )

    out = StringIO()
    call_command("audit_prune", days=365, dry_run=True, stdout=out)
    assert "Would delete 2 audit entries" in out.getvalue()
    assert AuditEntry.objects.count() == 3

    out = StringIO()
    call_command("audit_prune", days=365, model="testapp.book", stdout=out, batch_size=1)
    assert "Deleted 1 audit entry" in out.getvalue()
    assert set(AuditEntry.objects.values_list("pk", flat=True)) == {author_entry.pk, recent.pk}

    call_command(
        "audit_prune",
        before=(timezone.now() - timedelta(days=30)).date().isoformat(),
        stdout=StringIO(),
    )
    assert list(AuditEntry.objects.values_list("pk", flat=True)) == [recent.pk]


def test_audit_prune_argument_errors():
    with pytest.raises(CommandError):
        call_command("audit_prune", days=-1)
    with pytest.raises(CommandError):
        call_command("audit_prune", before="not-a-date")
    with pytest.raises(CommandError):
        call_command("audit_prune", days=1, model="nodot")


# --- admin -------------------------------------------------------------------
def test_admin_is_read_only_and_renders_changes(book, admin_user):
    model_admin = AuditEntryAdmin(AuditEntry, site)
    request = RequestFactory().get("/admin/")
    request.user = admin_user
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False

    entry = AuditEntry.objects.for_object(book).get()
    html = model_admin.changes_table(entry)
    assert "<th>title</th>" in html and "&quot;Himu&quot;" in html
    assert model_admin.model_label(entry) == "testapp.book"


def test_admin_changelist_loads(book, admin_user, client):
    client.force_login(admin_user)
    response = client.get("/admin/audit_log/auditentry/")
    assert response.status_code == 200
    detail = client.get(f"/admin/audit_log/auditentry/{AuditEntry.objects.first().pk}/change/")
    assert detail.status_code == 200
    assert b"Before" in detail.content and b"After" in detail.content


# --- DRF ---------------------------------------------------------------------
def test_drf_viewset_filters_and_requires_admin(book, author, admin_user, user):
    client = APIClient()
    assert client.get("/api/audit/").status_code == 403
    client.force_authenticate(user=user)
    assert client.get("/api/audit/").status_code == 403

    client.force_authenticate(user=admin_user)
    everything = client.get("/api/audit/").json()
    assert everything["count"] == 2
    books_only = client.get("/api/audit/?model=testapp.book").json()
    assert books_only["count"] == 1
    assert books_only["results"][0]["model"] == "testapp.book"
    assert books_only["results"][0]["changes"]["title"] == [None, "Himu"]
    assert (
        client.get(f"/api/audit/?object_pk={author.pk}&model=testapp.author").json()["count"] == 1
    )
    assert client.get("/api/audit/?action=delete").json()["count"] == 0
    assert client.post("/api/audit/", {}).status_code == 405


# --- queryset helpers ----------------------------------------------------------
def test_queryset_helpers(author, user):
    from audit_log import audit_context

    with audit_context(actor=user):
        Author.objects.create(name="Second")
    assert AuditEntry.objects.by_actor(user).count() == 1
    assert AuditEntry.objects.for_model(Author).count() == 2
    assert AuditEntry.objects.older_than(timezone.now() + timedelta(seconds=1)).count() == 2
