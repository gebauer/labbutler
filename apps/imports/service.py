"""Import orchestration: turn a LabSuit workbook into a previewable, committable plan.

The flow is two-phase by design: build a :class:`ImportPlan` (a pure, read-only dry run
that reports "N OK, M warnings, K errors"), then optionally :func:`commit` it inside a
single transaction. Imported items keep their original LabSuit serial as their frozen
human identifier, so no physical container is relabelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from django.db import transaction

from apps.audit.models import AuditEntry
from apps.inventory.models import (
    FieldDefinition,
    HazardStatement,
    Item,
    Location,
    Tag,
)
from apps.procurement.models import Vendor
from apps.tenancy.models import Lab, User

from . import labsuit, parsers


@dataclass
class ParsedRow:
    """One resolved spreadsheet row plus its diagnostics."""

    sheet: str
    row_number: int
    legacy_serial: str = ""
    human_id: str = ""
    fields: dict = field(default_factory=dict)  # direct Item field kwargs
    custom_fields: dict = field(default_factory=dict)
    location_path: list = field(default_factory=list)
    tag_names: list = field(default_factory=list)
    hazard_codes: list = field(default_factory=list)
    field_pool_keys: list = field(default_factory=list)  # extra cols -> custom-field pool
    owner_email: str = ""
    vendor_name: str = ""
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    skip: bool = False  # row flagged Delete? = y

    @property
    def ok(self) -> bool:
        return not self.errors and not self.skip


@dataclass
class ImportPlan:
    rows: list[ParsedRow] = field(default_factory=list)

    @property
    def ok_rows(self) -> list[ParsedRow]:
        return [r for r in self.rows if r.ok]

    def counts(self) -> dict[str, int]:
        ok = sum(1 for r in self.rows if r.ok)
        warnings = sum(1 for r in self.rows if r.ok and r.warnings)
        errors = sum(1 for r in self.rows if r.errors)
        skipped = sum(1 for r in self.rows if r.skip)
        return {"ok": ok, "warnings": warnings, "errors": errors, "skipped": skipped}

    def summary(self) -> str:
        c = self.counts()
        return (
            f"{c['ok']:,} OK, {c['warnings']:,} warnings, "
            f"{c['errors']:,} errors, {c['skipped']:,} skipped"
        )


def _truthy_yn(value: object) -> bool:
    return str(value).strip().lower() in {"y", "yes", "true", "1"}


def _parse_row(raw: labsuit.LabSuitRow) -> ParsedRow:
    values = raw.values
    row = ParsedRow(sheet=raw.sheet, row_number=raw.row_number)

    if _truthy_yn(values.get("Delete? (y/n)")):
        row.skip = True
        row.warnings.append("flagged Delete? = y")

    serial = str(values.get("SERIAL_NUMBER", "")).strip()
    name = str(values.get("NAME", "")).strip()
    if not serial:
        row.errors.append("missing SERIAL_NUMBER")
    if not name:
        row.errors.append("missing NAME")
    row.legacy_serial = serial
    row.fields["legacy_serial"] = serial
    row.fields["name"] = name
    if name.lower() == "test":
        row.warnings.append("looks like a junk row (name 'test')")

    # Direct field copies.
    for column, model_field in labsuit.CORE_TO_FIELD.items():
        if column in ("SERIAL_NUMBER", "NAME"):
            continue
        if column in values:
            row.fields[model_field] = str(values[column]).strip()

    # Price.
    if "PRICE" in values:
        price = parsers.parse_price(values["PRICE"])
        if price.warning:
            row.warnings.append(price.warning)
        if price.amount is not None:
            row.fields["price_amount"] = price.amount
            row.fields["price_currency"] = price.currency

    # Expiration date.
    if "EXPIRATION_DATE" in values:
        parsed_date = parsers.parse_european_date(values["EXPIRATION_DATE"])
        if parsed_date is None:
            row.warnings.append(f"unparseable expiration date: {values['EXPIRATION_DATE']!r}")
        else:
            row.fields["expiration_date"] = parsed_date

    # Hazard soup.
    tags = parsers.parse_tags(values.get("TAGS"))
    row.hazard_codes = tags.hazard_codes
    row.fields["signal_word"] = tags.signal_word
    row.fields["wgk"] = tags.wgk
    row.fields["storage_class"] = tags.storage_class
    row.tag_names = list(tags.tags)
    # The sheet name itself becomes a tag.
    if raw.sheet not in row.tag_names:
        row.tag_names.append(raw.sheet)

    # Location hierarchy.
    row.location_path = parsers.parse_location_path(
        values.get("LOCATION"), values.get("SUB_LOCATION"), values.get("SUB_LOCATION2")
    )

    # Owner + supplier relations.
    owner = str(values.get("OWNER", "")).strip()
    if owner:
        if "@" in owner:
            row.owner_email = owner.lower()
        else:
            row.warnings.append(f"owner is not an email: {owner!r}")
    row.vendor_name = str(values.get("SUPPLIER", "")).strip()

    # Amount in stock (container-level model stores no quantity; flag junk).
    if "AMOUNT_IN_STOCK" in values:
        amount = parsers.parse_amount_in_stock(values["AMOUNT_IN_STOCK"])
        if amount.warning:
            row.warnings.append(amount.warning)

    # Pass-through core columns -> custom_fields (no pool definition).
    for column in labsuit.CORE_PASSTHROUGH:
        if column in values:
            row.custom_fields[column.lower()] = str(values[column]).strip()

    # Extra (type-specific) columns -> custom_fields + lab custom-field pool.
    for column in raw.extra_columns:
        if column in values:
            key = column.strip().lower().replace(" ", "_")
            row.custom_fields[key] = str(values[column]).strip()
            row.field_pool_keys.append((key, column.strip()))

    return row


def build_plan(path: str | Path) -> ImportPlan:
    """Dry run: parse the whole workbook and resolve per-row human IDs (no DB writes).

    Intra-file legacy-serial collisions (the same serial on two sheets — tolerated, as
    the surrogate key carries identity) are disambiguated into distinct human IDs and
    flagged, so two physical containers are never silently merged.
    """
    plan = ImportPlan()
    seen_serials: dict[str, int] = {}
    for raw in labsuit.iter_rows(path):
        row = _parse_row(raw)
        if row.legacy_serial:
            count = seen_serials.get(row.legacy_serial, 0) + 1
            seen_serials[row.legacy_serial] = count
            if count == 1:
                row.human_id = row.legacy_serial
            else:
                row.human_id = f"{row.legacy_serial}#{count}"
                row.warnings.append(
                    f"duplicate serial {row.legacy_serial!r}; imported as {row.human_id}"
                )
        plan.rows.append(row)
    return plan


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0


def _resolve_location(lab: Lab, levels: list[parsers.LocationLevel]) -> Location | None:
    parent = None
    leaf = None
    for level in levels:
        leaf, _ = Location.objects.get_or_create(
            lab=lab,
            parent=parent,
            name=level.name,
            defaults={"room_number": level.room_number},
        )
        parent = leaf
    return leaf


def _hazard_kind(code: str) -> str:
    if code.startswith("EUH"):
        return HazardStatement.Kind.EUH
    if code.startswith("P"):
        return HazardStatement.Kind.P
    return HazardStatement.Kind.H


@transaction.atomic
def commit(plan: ImportPlan, *, lab: Lab, actor: User | None = None) -> ImportResult:
    """Persist the OK rows of a plan into ``lab`` within a single transaction.

    Upserts on (lab, human_id): re-importing the same workbook updates rather than
    duplicates. Builds the location hierarchy, registers extra columns in the custom-field
    pool, and links tags, hazards, vendor, and a (stub if needed) owner user.
    """
    result = ImportResult()
    for row in plan.rows:
        if not row.ok:
            result.skipped += 1
            continue

        location = _resolve_location(lab, row.location_path)

        vendor = None
        if row.vendor_name:
            vendor, _ = Vendor.objects.get_or_create(lab=lab, name=row.vendor_name)

        owner = None
        if row.owner_email:
            owner, _ = User.objects.get_or_create(
                email=row.owner_email, defaults={"username": row.owner_email}
            )

        # Register extra columns in the lab custom-field pool.
        for key, label in row.field_pool_keys:
            FieldDefinition.objects.get_or_create(
                lab=lab, key=key, defaults={"label": label}
            )

        defaults = dict(row.fields)
        defaults.update(
            location=location,
            vendor=vendor,
            owner=owner,
            custom_fields=row.custom_fields,
        )
        item, created = Item.objects.update_or_create(
            lab=lab, human_id=row.human_id, defaults=defaults
        )

        tags = [Tag.objects.get_or_create(lab=lab, name=name)[0] for name in row.tag_names]
        item.tags.set(tags)
        hazards = [
            HazardStatement.objects.get_or_create(
                code=code, defaults={"kind": _hazard_kind(code)}
            )[0]
            for code in row.hazard_codes
        ]
        item.hazards.set(hazards)

        if created:
            result.created += 1
        else:
            result.updated += 1

    AuditEntry.record(
        lab=lab,
        actor=actor,
        action="inventory.imported",
        target=("Import", lab.pk),
        changes={
            "created": result.created,
            "updated": result.updated,
            "skipped": result.skipped,
        },
    )
    return result
