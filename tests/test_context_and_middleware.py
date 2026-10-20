import pytest
from django.test import Client

from audit_log import audit_context, disable_auditing, get_context, set_actor
from audit_log.models import AuditEntry
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db


def test_audit_context_sets_actor_and_request_id(user):
    with audit_context(actor=user, request_id="cmd-42", ip="10.0.0.9", source="import"):
        author = Author.objects.create(name="With context")
    entry = AuditEntry.objects.for_object(author).get()
    assert entry.actor == user
    assert entry.actor_repr == "nadia"
    assert entry.request_id == "cmd-42"
    assert entry.ip == "10.0.0.9"
    assert entry.extra == {"source": "import"}
    # context is restored afterwards
    assert get_context().actor is None and get_context().request_id == ""


def test_nested_context_inherits_and_overrides(user):
    with audit_context(actor=user, request_id="outer"):
        with audit_context(request_id="inner"):
            ctx = get_context()
            assert ctx.actor == user and ctx.request_id == "inner"
        assert get_context().request_id == "outer"


def test_set_actor_without_user_instance():
    with audit_context():
        set_actor("cron", actor_repr="nightly-job")
        author = Author.objects.create(name="Cron made me")
    entry = AuditEntry.objects.for_object(author).get()
    assert entry.actor is None and entry.actor_repr == "nightly-job"


def test_disable_auditing_suppresses_entries(author):
    with disable_auditing():
        author.name = "quietly renamed"
        author.save()
        Author.objects.create(name="also quiet")
    assert AuditEntry.objects.count() == 1  # only the fixture's create
    author.name = "loud again"
    author.save()
    assert AuditEntry.objects.count() == 2


def test_middleware_captures_user_ip_agent_and_request_id(book, user):
    client = Client(
        HTTP_USER_AGENT="pytest-client/1.0",
        HTTP_X_REQUEST_ID="abc-123",
        HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1",
        REMOTE_ADDR="10.0.0.1",
    )
    client.force_login(user)
    response = client.get(f"/books/{book.pk}/rename/?title=Himur Hate Koyekti Neel Poddo")
    assert response.status_code == 200
    assert response["X-Request-ID"] == "abc-123"

    entry = AuditEntry.objects.for_object(book).filter(action="update").get()
    assert entry.actor == user
    assert entry.actor_repr == "nadia"
    assert entry.ip == "203.0.113.7"
    assert entry.user_agent == "pytest-client/1.0"
    assert entry.request_id == "abc-123"
    assert entry.extra == {"path": f"/books/{book.pk}/rename/", "method": "GET"}


def test_middleware_anonymous_and_generated_request_id(book):
    client = Client(REMOTE_ADDR="192.0.2.10")
    response = client.get(f"/books/{book.pk}/rename/?title=Anon")
    generated = response["X-Request-ID"]
    assert len(generated) == 32
    entry = AuditEntry.objects.for_object(book).filter(action="update").get()
    assert entry.actor is None and entry.actor_repr == ""
    assert entry.ip == "192.0.2.10"
    assert entry.request_id == generated


def test_middleware_context_is_cleared_after_request(book):
    Client().get(f"/books/{book.pk}/rename/?title=X")
    assert get_context().request_id == ""


def test_x_forwarded_for_can_be_distrusted(book, settings):
    settings.AUDIT_LOG = {"TRUST_X_FORWARDED_FOR": False}
    client = Client(HTTP_X_FORWARDED_FOR="203.0.113.7", REMOTE_ADDR="10.0.0.1")
    client.get(f"/books/{book.pk}/rename/?title=Y")
    entry = AuditEntry.objects.for_object(book).filter(action="update").get()
    assert entry.ip == "10.0.0.1"
