import pytest

from audit_log.models import AuditEntry

pytestmark = pytest.mark.django_db


def m2m_entries(book):
    return list(AuditEntry.objects.for_object(book).filter(action__startswith="m2m").order_by("id"))


def test_m2m_add_remove_clear(book, tags):
    fiction, bangla, classic = tags
    book.tags.add(fiction, bangla)
    book.tags.remove(fiction)
    book.tags.clear()

    entries = m2m_entries(book)
    assert [e.action for e in entries] == ["m2m_add", "m2m_remove", "m2m_clear"]
    add, remove, clear = entries
    assert add.changes == {
        "tags": {
            "action": "add",
            "objects": sorted([fiction.pk, bangla.pk]),
            "related_model": "testapp.tag",
        }
    }
    assert remove.changes["tags"]["objects"] == [fiction.pk]
    assert clear.changes["tags"] == {
        "action": "clear",
        "objects": [],
        "related_model": "testapp.tag",
    }


def test_m2m_set_produces_add_and_remove(book, tags):
    fiction, bangla, classic = tags
    book.tags.set([fiction, bangla])
    book.tags.set([classic])
    actions = [e.action for e in m2m_entries(book)]
    assert actions == ["m2m_add", "m2m_remove", "m2m_add"]


def test_reverse_side_changes_are_not_attributed(book, tags):
    fiction = tags[0]
    fiction.books.add(book)
    assert m2m_entries(book) == []
    assert AuditEntry.objects.for_object(fiction).count() == 0  # Tag is not registered


def test_m2m_entries_carry_context(book, tags, user):
    from audit_log import audit_context

    with audit_context(actor=user, request_id="req-m2m"):
        book.tags.add(tags[0])
    entry = m2m_entries(book)[0]
    assert entry.actor == user and entry.actor_repr == "nadia" and entry.request_id == "req-m2m"


def test_adding_already_related_objects_writes_nothing(book, tags):
    book.tags.add(tags[0])
    book.tags.add(tags[0])  # Django reports an empty pk_set: nothing changed, nothing logged
    book.tags.add()
    assert [e.action for e in m2m_entries(book)] == ["m2m_add"]
