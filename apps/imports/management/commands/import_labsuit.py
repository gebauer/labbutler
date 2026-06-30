"""Import a LabSuit workbook into a lab.

    # dry run (default): just print the preview
    uv run python manage.py import_labsuit path/to/export.xlsx --lab ag-baumann

    # actually write the items
    uv run python manage.py import_labsuit path/to/export.xlsx --lab ag-baumann --commit
"""

from django.core.management.base import BaseCommand, CommandError

from apps.imports.service import build_plan, commit
from apps.tenancy.models import Lab


class Command(BaseCommand):
    help = "Dry-run or commit a LabSuit spreadsheet import into a lab."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the LabSuit .xlsx export")
        parser.add_argument("--lab", required=True, help="Target lab slug")
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Write the items (default is a read-only dry run).",
        )
        parser.add_argument(
            "--show", type=int, default=10, help="How many warning/error rows to list."
        )

    def handle(self, *args, **opts):
        try:
            lab = Lab.objects.get(slug=opts["lab"])
        except Lab.DoesNotExist:
            raise CommandError(f"No lab with slug {opts['lab']!r}") from None

        plan = build_plan(opts["path"])
        self.stdout.write(self.style.MIGRATE_HEADING(f"Dry run: {plan.summary()}"))

        flagged = [r for r in plan.rows if r.errors or r.warnings]
        for row in flagged[: opts["show"]]:
            tag = self.style.ERROR("ERROR") if row.errors else self.style.WARNING("warn")
            issues = "; ".join(row.errors + row.warnings)
            self.stdout.write(f"  [{tag}] {row.sheet}:{row.row_number} {issues}")
        if len(flagged) > opts["show"]:
            self.stdout.write(f"  ... and {len(flagged) - opts['show']} more")

        if not opts["commit"]:
            self.stdout.write("Dry run only. Re-run with --commit to write items.")
            return

        result = commit(plan, lab=lab)
        self.stdout.write(
            self.style.SUCCESS(
                f"Committed: {result.created} created, {result.updated} updated, "
                f"{result.skipped} skipped."
            )
        )
