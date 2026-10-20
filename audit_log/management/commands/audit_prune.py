"""Delete old audit entries in batches.

python manage.py audit_prune --days 365
python manage.py audit_prune --before 2025-01-01 --model shop.order --dry-run
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from audit_log.models import AuditEntry


class Command(BaseCommand):
    help = "Delete audit entries older than a retention threshold."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--days", type=int, help="Delete entries older than N days.")
        group.add_argument(
            "--before", type=str, help="Delete entries before this ISO date/datetime."
        )
        parser.add_argument(
            "--model", type=str, help="Restrict to app_label.model (e.g. shop.order)."
        )
        parser.add_argument("--batch-size", type=int, default=5000)
        parser.add_argument(
            "--dry-run", action="store_true", help="Only report what would be deleted."
        )

    def handle(self, *args, **options):
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

        queryset = AuditEntry.objects.older_than(cutoff)
        if options["model"]:
            app_label, _, model_name = options["model"].lower().partition(".")
            if not model_name:
                raise CommandError("--model must look like app_label.model")
            queryset = queryset.filter(
                content_type__app_label=app_label, content_type__model=model_name
            )

        total = queryset.count()
        if options["dry_run"]:
            self.stdout.write(
                f"Would delete {total} audit entr{'y' if total == 1 else 'ies'} "
                f"older than {cutoff.isoformat()}."
            )
            return

        deleted = 0
        batch_size = max(1, options["batch_size"])
        while True:
            pks = list(queryset.order_by("pk").values_list("pk", flat=True)[:batch_size])
            if not pks:
                break
            count, _ = AuditEntry.objects.filter(pk__in=pks).delete()
            deleted += count
        noun = "entry" if deleted == 1 else "entries"
        self.stdout.write(
            self.style.SUCCESS(f"Deleted {deleted} audit {noun} older than {cutoff.isoformat()}.")
        )
