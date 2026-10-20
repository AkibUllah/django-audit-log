from datetime import date
from decimal import Decimal

import pytest

import audit_log
from audit_log.diff import diff, serialize_value, snapshot, tracked_fields
from audit_log.models import AuditEntry
from audit_log.registry import AlreadyRegistered, NotRegistered, registry
from tests.testapp.models import Author, Book, Customer, Untracked

pytestmark = pytest.mark.django_db


def entries_for(obj):
    return list(AuditEntry.objects.for_object(obj).order_by("id"))


def test_create_records_full_snapshot(author):
    (entry,) = entries_for(author)
    assert entry.action == "create"
    assert entry.object_pk == str(author.pk)
    assert entry.object_repr == "Humayun Ahmed"
    assert entry.model_label == "testapp.author"
    assert entry.changes == {"name": [None, "Humayun Ahmed"], "born": [None, "1948-11-13"]}
    assert entry.changed_fields == ["born", "name"]


def test_update_records_only_changed_fields(book):
    book.price = Decimal("299.50")
    book.in_print = False
    book.save()
    entries = entries_for(book)
    assert [e.action for e in entries] == ["create", "update"]
    assert entries[1].changes == {"price": ["250.00", "299.50"], "in_print": [True, False]}


def test_no_entry_when_nothing_changed(book):
    book.save()
    book.title = "Himu"
    book.save()
    assert [e.action for e in entries_for(book)] == ["create"]


def test_excluded_field_is_not_tracked(book):
    # updated_at (auto_now) changes on every save but is excluded for Book
    create = entries_for(book)[0]
    assert "updated_at" not in create.changes
    assert tracked_fields(Book, None, {"updated_at"}) == [
        "title",
        "author",
        "price",
        "published",
        "in_print",
    ]


def test_fields_whitelist_limits_tracking(customer):
    customer.notes = "changed"
    customer.save()
    assert len(entries_for(customer)) == 1  # notes is outside fields=[...]
    assert "notes" not in entries_for(customer)[0].changes


def test_foreign_key_recorded_as_pk(book, author):
    other = Author.objects.create(name="Sunil Gangopadhyay")
    book.author = other
    book.save()
    update = entries_for(book)[-1]
    assert update.changes == {"author": [author.pk, other.pk]}


def test_delete_records_last_known_values(book):
    pk = book.pk
    book.delete()
    entry = AuditEntry.objects.filter(object_pk=str(pk), action="delete").get()
    assert entry.changes["title"] == ["Himu", None]
    assert entry.changes["price"] == ["250.00", None]


def test_masking_hides_values_but_shows_change(customer):
    create = entries_for(customer)[0]
    assert create.changes["nid_number"] == [None, "[hidden]"]
    assert create.changes["phone"] == [None, "[hidden]"]
    assert create.changes["name"] == [None, "Rahim Uddin"]

    customer.phone = "01999999999"
    customer.balance = Decimal("1200.00")
    customer.save()
    update = entries_for(customer)[-1]
    assert update.changes == {"phone": ["[hidden]", "[hidden]"], "balance": ["1500.00", "1200.00"]}


def test_untracked_model_writes_nothing(db):
    Untracked.objects.create(value="x")
    assert AuditEntry.objects.for_model(Untracked).count() == 0


def test_serialize_value_covers_common_types(author):
    assert serialize_value(Decimal("1.50")) == "1.50"
    assert serialize_value(date(2026, 1, 2)) == "2026-01-02"
    assert serialize_value(author) == author.pk
    assert serialize_value({"a": [Decimal("1"), None]}) == {"a": ["1", None]}
    assert serialize_value(b"\x01\x02") == "0102"
    assert serialize_value(True) is True


def test_diff_helpers():
    assert diff({"a": 1, "b": 2}, {"a": 1, "b": 3}, set()) == {"b": [2, 3]}
    assert diff(None, {"a": 1}, set()) == {"a": [None, 1]}
    assert diff({"a": 1}, None, {"a"}) == {"a": ["[hidden]", None]}
    assert snapshot(Author(name="x", born=None), ["name", "born"]) == {"name": "x", "born": None}


def test_registry_guards():
    with pytest.raises(AlreadyRegistered):
        audit_log.register(Book)
    with pytest.raises(NotRegistered):
        registry.get_config(Untracked)
    with pytest.raises(ValueError, match="no field"):
        audit_log.register(Untracked, exclude=["nope"])
    assert audit_log.is_registered(Customer)
    assert registry.get_config(Customer).mask == frozenset({"nid_number", "phone"})


def test_unregister_and_decorator_roundtrip(db):
    audit_log.unregister(Author)
    try:
        Author.objects.create(name="silent")
        assert AuditEntry.objects.for_model(Author).count() == 0
    finally:
        audit_log.audited(Author)
    Author.objects.create(name="loud")
    assert AuditEntry.objects.for_model(Author).count() == 1


def test_decorator_with_options_registers(db):
    audit_log.unregister(Customer)
    try:
        decorated = audit_log.audited(mask=["phone"])(Customer)
        assert decorated is Customer
        assert registry.get_config(Customer).mask == frozenset({"phone"})
    finally:
        audit_log.unregister(Customer)
        audit_log.register(
            Customer,
            mask=["nid_number", "phone"],
            fields=["name", "nid_number", "phone", "balance"],
        )


def test_raw_fixture_loads_are_ignored(db):
    from django.core import serializers

    author = Author.objects.create(name="Fixture")
    AuditEntry.objects.all().delete()
    payload = serializers.serialize("json", [author])
    for obj in serializers.deserialize("json", payload):
        obj.save()  # raw=True
    assert AuditEntry.objects.count() == 0
