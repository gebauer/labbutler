"""Align imported requests' created/updated timestamps to their workflow dates.

Requests imported from LabSuit all carry the import moment as their ``created_at``, so the
request list (ordered by ``-created_at``) can't reflect when each order actually happened.
This one-off, idempotent command rewrites the timestamps from the stored workflow dates.

    uv run python manage.py backfill_order_timestamps --lab ag-baumann

Only requests that have at least one historical date are touched, so requests created
in-app (all dates blank) are left alone.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.imports.orders_service import _ACTIVITY_DATE_FIELDS, align_timestamps
from apps.procurement.models import Request
from apps.tenancy.models import Lab


class Command(BaseCommand):
    help = "Rewrite imported requests' timestamps from their historical workflow dates."

    def add_arguments(self, parser):
        parser.add_argument("--lab", required=True, help="Target lab slug")

    def handle(self, *args, **opts):
        try:
            lab = Lab.objects.get(slug=opts["lab"])
        except Lab.DoesNotExist:
            raise CommandError(f"No lab with slug {opts['lab']!r}") from None

        has_any_date = Q()
        for field_name in _ACTIVITY_DATE_FIELDS:
            has_any_date |= Q(**{f"{field_name}__isnull": False})

        updated = 0
        for request in Request.objects.filter(lab=lab).filter(has_any_date).iterator():
            if align_timestamps(request):
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Aligned timestamps on {updated} requests."))
