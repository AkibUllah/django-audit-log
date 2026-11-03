from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from io import StringIO
from unittest import mock

import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command
from django.test import override_settings

from audit_log.checks import check_retention_models
from audit_log.models import AuditEntry
from audit_log.retention import get_policy, parse_policy
from tests.testapp.models import Author, Book, Customer

POLICY = {
    "default": 365,
    "update": 180,
    "delete": 3650,
    "bulk_delete": None,
    "models": {
        "testapp.book": {"default": 30},
        "TestApp.Customer": {"update": 730, "m2m_add": None},
    },
}


# --- parsing and resolution ----------------------------------------------------
def test_unset_policy_is_none():
    assert parse_policy(None) is None
    assert get_policy() is None


def test_days_for_prefers_the_most_specific_rule():
    policy = parse_policy(POLICY)
    # global action rules, then the global default
    assert policy.days_for("testapp.author", "update") == 180
    assert policy.days_for("testapp.author", "delete") == 3650
    assert policy.days_for("testapp.author", "create") == 365
    assert policy.days_for("testapp.author", "bulk_delete") is None
    # a model default beats the global action rules
    assert policy.days_for("testapp.book", "delete") == 30
    assert policy.days_for("testapp.book", "bulk_delete") == 30
    # model + action beats everything; actions the model does not name fall through
    assert policy.days_for("testapp.customer", "update") == 730
    assert policy.days_for("testapp.customer", "m2m_add") is None
    assert policy.days_for("testapp.customer", "delete") == 3650
    assert policy.days_for("TESTAPP.Customer", "create") == 365


def test_without_a_global_default_unmatched_entries_are_kept_forever():
    policy = parse_policy({"update": 90})
    assert policy.days_for("testapp.author", "update") == 90
    assert policy.days_for("testapp.author", "delete") is None


def test_zero_days_is_allowed():
    assert parse_policy({"default": 0}).days_for("testapp.author", "create") == 0


@override_settings(AUDIT_LOG={"RETENTION": {"default": 7}})
def test_get_policy_reads_settings():
    assert get_policy().default == 7


# --- validation ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([("default", 1)], "must be a dict"),
        ({"updated": 10}, "unknown key 'updated'"),
        ({"default": "365"}, "['default'] must be a whole number of days"),
        ({"delete": 1.5}, "['delete'] must be a whole number of days"),
        ({"delete": True}, "['delete'] must be a whole number of days"),
        ({"update": -1}, "['update'] must be >= 0"),
        ({"models": ["testapp.book"]}, "['models'] must be a dict"),
        ({"models": {"book": {"default": 1}}}, "key 'book' must look like 'app_label.model'"),
        ({"models": {"testapp.book": 30}}, "['models']['testapp.book'] must be a non-empty dict"),
        ({"models": {"testapp.book": {}}}, "must be a non-empty dict"),
        ({"models": {"testapp.book": {"models": {}}}}, "unknown key 'models'"),
        (
            {"models": {"testapp.book": {"update": -5}}},
            "['models']['testapp.book']['update'] must be >= 0",
        ),
        (
            {"models": {"testapp.book": {"default": 1}, "TestApp.Book": {"default": 2}}},
            "lists 'testapp.book' more than once",
        ),
    ],
)
def test_invalid_policies_raise_a_clear_error(raw, message):
    with pytest.raises(ImproperlyConfigured) as excinfo:
        parse_policy(raw)
    assert message in str(excinfo.value)
    assert "AUDIT_LOG['RETENTION']" in str(excinfo.value)


# --- startup validation ----------------------------------------------------------
@override_settings(AUDIT_LOG={"RETENTION": {"delete": "forever"}})
def test_invalid_policy_fails_app_startup():
    with pytest.raises(ImproperlyConfigured, match=r"\['delete'\] must be a whole number"):
        apps.get_app_config("audit_log").ready()


@override_settings(AUDIT_LOG={"RETENTION": POLICY})
def test_valid_policy_passes_startup_and_checks():
    apps.get_app_config("audit_log").ready()
    assert check_retention_models() == []


@override_settings(AUDIT_LOG={"RETENTION": {"models": {"testapp.boook": {"default": 1}}}})
def test_unknown_model_label_is_a_system_check_warning():
    messages = run_checks()
    warnings = [m for m in messages if m.id == "audit_log.W001"]
    assert len(warnings) == 1
    assert "'testapp.boook'" in warnings[0].msg


def test_checks_are_silent_without_a_policy():
    assert check_retention_models() == []


# --- classes and the expired() helper (frozen time) --------------------------------
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=dt_timezone.utc)


@pytest.fixture
def frozen_now():
    with mock.patch("django.utils.timezone.now", return_value=NOW):
        yield NOW


def make_entry(model, action, age_days, seconds=0):
    return AuditEntry.objects.create(
        action=action,
        content_type=ContentType.objects.get_for_model(model),
        object_pk="1",
        timestamp=NOW - timedelta(days=age_days, seconds=seconds),
    )


def test_classes_partition_entries_and_agree_with_days_for(db):
    policy = parse_policy(POLICY)
    for model in (Author, Book, Customer):
        for action in AuditEntry.Action.values:
            make_entry(model, action, age_days=1)

    classes = policy.classes()
    assert [c.name for c in classes] == [
        "testapp.book",
        "testapp.customer:update",
        "testapp.customer:m2m_add",
        "update",
        "delete",
        "bulk_delete",
        "default",
    ]
    for entry in AuditEntry.objects.all():
        matching = [c for c in classes if AuditEntry.objects.filter(c.filter, pk=entry.pk).exists()]
        assert len(matching) == 1, (entry.model_label, entry.action, matching)
        assert matching[0].days == policy.days_for(entry.model_label, entry.action)


@pytest.mark.parametrize(
    ("model", "action", "days"),
    [
        (Author, "create", 365),  # global default
        (Author, "update", 180),  # action class
        (Author, "delete", 3650),  # action class
        (Book, "delete", 30),  # model default beats the action class
        (Customer, "update", 730),  # model + action
        (Customer, "delete", 3650),  # falls through to the action class
    ],
)
def test_expired_respects_each_class_boundary(db, frozen_now, model, action, days):
    on_the_edge = make_entry(model, action, age_days=days)
    past_it = make_entry(model, action, age_days=days, seconds=1)

    expired = AuditEntry.objects.expired(policy=parse_policy(POLICY))
    assert list(expired.values_list("pk", flat=True)) == [past_it.pk]
    assert on_the_edge.pk not in expired.values_list("pk", flat=True)


def test_keep_forever_classes_never_expire(db, frozen_now):
    make_entry(Author, "bulk_delete", age_days=100_000)
    make_entry(Customer, "m2m_add", age_days=100_000)
    assert not AuditEntry.objects.expired(policy=parse_policy(POLICY)).exists()


def test_expired_uses_the_configured_policy_and_explicit_now(db, frozen_now):
    entry = make_entry(Author, "update", age_days=10)
    with override_settings(AUDIT_LOG={"RETENTION": {"update": 7}}):
        assert list(AuditEntry.objects.expired()) == [entry]
        assert not AuditEntry.objects.expired(now=NOW - timedelta(days=5)).exists()
    # composes with the other helpers
    assert (
        AuditEntry.objects.for_model(Book).expired(policy=parse_policy({"default": 0})).count() == 0
    )


def test_expired_is_empty_without_a_policy_or_with_only_forever_rules(db, frozen_now):
    make_entry(Author, "update", age_days=10_000)
    assert not AuditEntry.objects.expired().exists()
    assert not AuditEntry.objects.expired(policy=parse_policy({"default": None})).exists()
    assert parse_policy({"default": None}).expired_filter(NOW) is None


# --- audit_prune --policy ---------------------------------------------------------------
def _prune(**options):
    out = StringIO()
    call_command("audit_prune", policy=True, stdout=out, **options)
    return out.getvalue()


def _class_rows(output):
    rows = {}
    for line in output.splitlines()[1:]:
        if line.startswith("  "):
            name, *rest = line.split()
            rows[name] = rest[-1]
    return rows


@pytest.fixture
def aged_entries(db, frozen_now):
    return {
        "author_create_old": make_entry(Author, "create", 400),
        "author_create_new": make_entry(Author, "create", 300),
        "author_update_old": make_entry(Author, "update", 200),
        "author_delete_kept": make_entry(Author, "delete", 3000),
        "author_bulk_delete": make_entry(Author, "bulk_delete", 9000),
        "book_delete_old": make_entry(Book, "delete", 31),
        "book_create_new": make_entry(Book, "create", 29),
        "customer_update_old": make_entry(Customer, "update", 731),
        "customer_update_new": make_entry(Customer, "update", 700),
    }


EXPIRED = {"author_create_old", "author_update_old", "book_delete_old", "customer_update_old"}


@override_settings(AUDIT_LOG={"RETENTION": POLICY})
def test_policy_dry_run_lists_counts_per_class(aged_entries):
    output = _prune(dry_run=True)
    assert _class_rows(output) == {
        "testapp.book": "1",
        "testapp.customer:update": "1",
        "testapp.customer:m2m_add": "-",
        "update": "1",
        "delete": "0",
        "bulk_delete": "-",
        "default": "1",
    }
    assert "forever" in output and "365 days" in output
    assert "Would delete 4 audit entries under the retention policy." in output
    assert AuditEntry.objects.count() == len(aged_entries)


@override_settings(AUDIT_LOG={"RETENTION": POLICY})
def test_policy_prune_deletes_only_expired_entries_in_batches(aged_entries):
    output = _prune(batch_size=1)
    assert "Deleted 4 audit entries under the retention policy." in output
    assert _class_rows(output)["default"] == "1"
    remaining = set(AuditEntry.objects.values_list("pk", flat=True))
    assert remaining == {e.pk for k, e in aged_entries.items() if k not in EXPIRED}

    assert "Deleted 0 audit entries" in _prune()  # idempotent


@override_settings(AUDIT_LOG={"RETENTION": POLICY})
def test_policy_prune_with_model_filter_skips_other_models_rules(aged_entries):
    output = _prune(model="TestApp.Book")
    rows = _class_rows(output)
    assert "testapp.customer:update" not in rows
    assert rows["testapp.book"] == "1"
    assert "Deleted 1 audit entry under the retention policy." in output
    assert not AuditEntry.objects.filter(pk=aged_entries["book_delete_old"].pk).exists()
    assert AuditEntry.objects.filter(pk=aged_entries["author_create_old"].pk).exists()


def test_policy_prune_errors(db):
    with pytest.raises(CommandError, match="needs AUDIT_LOG\\['RETENTION'\\]"):
        _prune()
    with override_settings(AUDIT_LOG={"RETENTION": {"default": -3}}):
        with pytest.raises(CommandError, match="must be >= 0"):
            _prune()
    with pytest.raises(CommandError, match="not allowed with"):
        call_command("audit_prune", "--policy", "--days", "30", stdout=StringIO())
    with override_settings(AUDIT_LOG={"RETENTION": POLICY}):
        with pytest.raises(CommandError, match="app_label.model"):
            _prune(model="book")


@override_settings(AUDIT_LOG={"RETENTION": POLICY})
def test_explicit_flags_still_work_with_a_policy_configured(aged_entries):
    out = StringIO()
    call_command("audit_prune", days=8000, stdout=out)
    assert "Deleted 1 audit entry" in out.getvalue()  # the bulk_delete kept forever by policy
