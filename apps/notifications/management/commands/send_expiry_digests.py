"""Send the item-expiry report now, synchronously.

Runs the same task the Celery beat schedule fires weekly, so it doubles as a manual
trigger and as a cron entry point on hosts that don't run celery beat.
"""

from django.core.management.base import BaseCommand

from apps.notifications.tasks import send_expiry_digests


class Command(BaseCommand):
    help = "Email each member their expiry report of expired and soon-to-expire items."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Look-ahead window in days (overrides each member's own setting).",
        )

    def handle(self, *args, **options) -> None:
        count = send_expiry_digests(days_ahead=options["days"])
        self.stdout.write(self.style.SUCCESS(f"Sent {count} expiry report email(s)."))
