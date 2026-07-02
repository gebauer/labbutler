"""Import a LabSuit *orders* workbook into a lab as procurement requests.

# dry run (default): just print the preview
uv run python manage.py import_labsuit_orders path/to/orders.xlsx --lab ag-baumann

# actually write the requests
uv run python manage.py import_labsuit_orders path/to/orders.xlsx --lab ag-baumann --commit

Orders have no stable identifier, so a --commit always creates: re-running duplicates
the requests rather than updating them.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.imports.orders_service import build_orders_plan, commit_orders
from apps.tenancy.models import Lab


class Command(BaseCommand):
    help = "Dry-run or commit a LabSuit orders spreadsheet import into a lab."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the LabSuit orders .xlsx export")
        parser.add_argument("--lab", required=True, help="Target lab slug")
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Write the requests (default is a read-only dry run).",
        )
        parser.add_argument(
            "--show", type=int, default=10, help="How many warning/error rows to list."
        )

    def handle(self, *args, **opts):
        try:
            lab = Lab.objects.get(slug=opts["lab"])
        except Lab.DoesNotExist:
            raise CommandError(f"No lab with slug {opts['lab']!r}") from None

        plan = build_orders_plan(opts["path"])
        self.stdout.write(self.style.MIGRATE_HEADING(f"Dry run: {plan.summary()}"))

        flagged = [r for r in plan.rows if r.errors or r.warnings]
        for row in flagged[: opts["show"]]:
            tag = self.style.ERROR("ERROR") if row.errors else self.style.WARNING("warn")
            issues = "; ".join(row.errors + row.warnings)
            self.stdout.write(f"  [{tag}] {row.sheet}:{row.row_number} {issues}")
        if len(flagged) > opts["show"]:
            self.stdout.write(f"  ... and {len(flagged) - opts['show']} more")

        if not opts["commit"]:
            self.stdout.write("Dry run only. Re-run with --commit to write requests.")
            return

        result = commit_orders(plan, lab=lab)
        self.stdout.write(
            self.style.SUCCESS(
                f"Committed: {result.created} requests created, {result.skipped} skipped."
            )
        )
