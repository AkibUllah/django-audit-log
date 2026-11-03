"""Delete old audit entries in batches.

python manage.py audit_prune --days 365
python manage.py audit_prune --before 2025-01-01 --model shop.order --dry-run
python manage.py audit_prune --policy --dry-run   # AUDIT_LOG["RETENTION"] classes
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from audit_log.models import AuditEntry
from audit_log.retention import get_policy


def _entries(count: int) -> str:
    return f"{count} audit entr{'y' if count == 1 else 'ies'}"


class Command(BaseCommand):
    help = "Delete audit entries older than a retention threshold or the retention policy."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--days", type=int, help="Delete entries older than N days.")
        group.add_argument(
            "--before", type=str, help="Delete entries before this ISO date/datetime."
        )
        group.add_argument(
            "--policy",
            action="store_true",
            help="Apply the retention classes from AUDIT_LOG['RETENTION'].",
        )
        parser.add_argument(
            "--model", type=str, help="Restrict to app_label.model (e.g. shop.order)."
        )
        parser.add_argument("--batch-size", type=int, default=5000)
        parser.add_argument(
            "--dry-run", action="store_true", help="Only report what would be deleted."
        )

    def handle(self, *args, **options):
        model_label = None
        queryset = AuditEntry.objects.all()
        if options["model"]:
            model_label = options["model"].lower()
            app_label, _, model_name = model_label.partition(".")
            if not model_name:
                raise CommandError("--model must look like app_label.model")
            queryset = queryset.filter(
                content_type__app_label=app_label, content_type__model=model_name
            )

        if options["policy"]:
            self._apply_policy(queryset, model_label, options)
            return

        if options["days"] is not None:
            if options["days"] < 0:
                raise CommandError("--days must be >= 0")
            cutoff = timezone.now() - timedelta(days=options["days"])
        else:
            try:
                parsed = datetime.fromisoformat(options["before"])
            except ValueError:
                raise CommandError("--before must be an ISO date, e.g. 2025-01-01")
            cutoff = parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)

        queryset = queryset.older_than(cutoff)
        if options["dry_run"]:
            total = queryset.count()
            self.stdout.write(f"Would delete {_entries(total)} older than {cutoff.isoformat()}.")
            return

        deleted = queryset.delete_in_batches(options["batch_size"])
        self.stdout.write(
            self.style.SUCCESS(f"Deleted {_entries(deleted)} older than {cutoff.isoformat()}.")
        )

    def _apply_policy(self, queryset, model_label: str | None, options) -> None:
        try:
            policy = get_policy()
        except ImproperlyConfigured as exc:
            raise CommandError(str(exc))
        if policy is None:
            raise CommandError("--policy needs AUDIT_LOG['RETENTION'] to be configured.")

        now = timezone.now()
        dry_run = options["dry_run"]
        rows: list[tuple[str, str, str]] = []
        total = 0
        for cls in policy.classes():
            if model_label and cls.model not in (None, model_label):
                continue  # a rule for another model cannot match the --model filter
            cutoff = cls.cutoff(now)
            if cutoff is None:
                rows.append((cls.name, "forever", "-"))
                continue
            expired = queryset.filter(cls.filter).older_than(cutoff)
            count = expired.count() if dry_run else expired.delete_in_batches(options["batch_size"])
            total += count
            rows.append((cls.name, f"{cls.days} days", str(count)))

        heading = ("class", "keep", "would delete" if dry_run else "deleted")
        widths = [max(len(row[i]) for row in [heading, *rows]) for i in range(3)]
        for row in [heading, *rows]:
            self.stdout.write(
                f"  {row[0].ljust(widths[0])}  {row[1].ljust(widths[1])}  {row[2].rjust(widths[2])}"
            )
        if dry_run:
            self.stdout.write(f"Would delete {_entries(total)} under the retention policy.")
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Deleted {_entries(total)} under the retention policy.")
            )
