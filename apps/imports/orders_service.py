"""Orders import orchestration: turn a LabSuit orders workbook into a previewable,
committable plan of :class:`~apps.procurement.models.Request` rows.

Mirrors :mod:`apps.imports.service` (the inventory importer): build a read-only
:class:`OrderImportPlan` dry run ("N OK, M warnings, K errors"), then optionally
:func:`commit_orders` it inside a single transaction. The sheet's own price/tax/total
figures are preserved verbatim (never recomputed) so imported history stays faithful to
LabSuit. Orders carry no stable external identifier, so a commit always *creates* — like
the generic inventory importer, re-running duplicates rather than updates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from django.db import transaction

from apps.audit.models import AuditEntry
from apps.inventory.models import Tag
from apps.procurement.models import Budget, Request, Vendor
from apps.tenancy.models import Lab, User

from . import orders, parsers

# LabSuit STATUS string -> Request.Status. "received" maps to Checked in (a terminal
# state) so a historical order can't be checked in again and spawn a duplicate item. The
# import sets the status directly and never runs the check-in service, so no inventory
# item is created and ``created_item`` stays empty — imported orders are left unlinked.
STATUS_MAP = {
    "requested": Request.Status.REQUESTED,
    "approved": Request.Status.APPROVED,
    "rejected": Request.Status.REJECTED,
    "ordered": Request.Status.ORDERED,
    "delivered": Request.Status.DELIVERED,
    "received": Request.Status.CHECKED_IN,
    "canceled": Request.Status.CANCELLED,
    "cancelled": Request.Status.CANCELLED,
}

# LabSuit date column -> Request field.
_DATE_FIELDS = {
    "DATE_REQUESTED": "date_requested",
    "DATE_APPROVED": "date_approved",
    "DATE_ORDERED": "date_ordered",
    "DATE_CANCELLED": "date_cancelled",
    "DATE_RECEIVED": "date_received",
}

# Columns with no dedicated Request field, folded into the comment for provenance.
_COMMENT_EXTRAS = [
    ("ITEM_TYPE", "Type"),
    ("MANUFACTURER", "Manufacturer"),
    ("PACK_SIZE", "Pack size"),
    ("REQUISITION_NUMBER", "Requisition #"),
    ("CONFIRMATION_NUMBER", "Confirmation #"),
    ("TRACKING_NUMBER", "Tracking #"),
    ("INVOICE_NUMBER", "Invoice #"),
    ("ORDERED_BY", "Ordered by"),
    ("RECEIVED_BY", "Received by"),
    ("CANCELLED_BY", "Cancelled by"),
    ("APPROVED_MESSAGE", "Approved msg"),
    ("ORDERED_MESSAGE", "Ordered msg"),
    ("CANCELLED_MESSAGE", "Cancelled msg"),
    ("RECEIVED_MESSAGE", "Received msg"),
]


@dataclass
class ParsedOrder:
    """One resolved orders row plus its diagnostics."""

    sheet: str
    row_number: int
    fields: dict = field(default_factory=dict)  # direct Request field kwargs
    vendor_name: str = ""
    budget_number: str = ""
    requested_by_email: str = ""
    approver_email: str = ""
    tag_names: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class OrderImportPlan:
    rows: list[ParsedOrder] = field(default_factory=list)

    @property
    def ok_rows(self) -> list[ParsedOrder]:
        return [r for r in self.rows if r.ok]

    def counts(self) -> dict[str, int]:
        ok = sum(1 for r in self.rows if r.ok)
        warnings = sum(1 for r in self.rows if r.ok and r.warnings)
        errors = sum(1 for r in self.rows if r.errors)
        return {"ok": ok, "warnings": warnings, "errors": errors}

    def summary(self) -> str:
        c = self.counts()
        return f"{c['ok']:,} OK, {c['warnings']:,} warnings, {c['errors']:,} errors"


def _text(values: dict, key: str) -> str:
    return str(values.get(key, "")).strip()


def _amount(raw: object) -> Decimal:
    """Best-effort money value (0 when absent/unparseable); reuses the price parser."""
    return parsers.parse_price(raw).amount or Decimal("0")


def _parse_pack_count(raw: object) -> int | None:
    """Coerce QUANTITY to a positive int; None if it isn't one."""
    if raw is None:
        return None
    text = str(raw).strip()
    try:
        value = int(float(text)) if text else 0
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _email(values: dict, column: str, row: ParsedOrder) -> str:
    raw = _text(values, column)
    if not raw:
        return ""
    if "@" in raw:
        return raw.lower()
    row.warnings.append(f"{column} is not an email: {raw!r}")
    return ""


# URLField length cap; over-long links are kept in the comment rather than truncated.
_URL_MAX = Request._meta.get_field("product_url").max_length


def _build_comment(values: dict, *, extra_url: str = "") -> str:
    parts = []
    base = _text(values, "COMMENTS")
    if base:
        parts.append(base)
    extras = [
        f"{label}: {str(values[column]).strip()}"
        for column, label in _COMMENT_EXTRAS
        if str(values.get(column, "")).strip()
    ]
    if extra_url:
        extras.append(f"URL: {extra_url}")
    if extras:
        parts.append("[LabSuit import] " + " · ".join(extras))
    return "\n\n".join(parts)


def _parse_order(raw: orders.OrderRow) -> ParsedOrder:
    values = raw.values
    row = ParsedOrder(sheet=raw.sheet, row_number=raw.row_number)

    name = _text(values, "ITEM_NAME")
    if not name:
        row.errors.append("missing ITEM_NAME")
    row.fields["item_name"] = name
    row.fields["catalog_number"] = _text(values, "CATALOG_NUMBER")
    row.fields["cas_number"] = _text(values, "CAS_NUMBER")
    row.fields["po_number"] = _text(values, "PURCHASE_ORDER_NUMBER")
    row.fields["quote_id"] = _text(values, "QUOTE_ID")

    # product_url is a URLField; accept a real http(s) link that fits, else keep the
    # link in the comment (truncating a URL would make it useless).
    url = _text(values, "URL")
    overflow_url = ""
    if url.startswith(("http://", "https://")):
        if len(url) <= _URL_MAX:
            row.fields["product_url"] = url
        else:
            overflow_url = url
            row.warnings.append("product URL too long for field; kept in comment")
    elif url:
        row.warnings.append(f"ignored non-URL product link: {url!r}")

    # Status.
    raw_status = _text(values, "STATUS").lower()
    status = STATUS_MAP.get(raw_status)
    if status is None:
        status = Request.Status.REQUESTED
        if raw_status:
            row.warnings.append(f"unknown status {raw_status!r}; imported as Requested")
    row.fields["status"] = status

    # Money: preserve the sheet's own figures (LabSuit prices are net, tax listed
    # separately), so tax/total are stored as-is and never recomputed.
    currency = _text(values, "CURRENCY").upper()
    price = parsers.parse_price(values.get("PRICE"))
    row.fields["unit_price"] = price.amount or Decimal("0")
    row.fields["currency"] = (currency or price.currency or "EUR")[:3]
    row.fields["tax"] = _amount(values.get("TAX"))
    row.fields["total"] = _amount(values.get("TOTAL"))
    row.fields["shipping_cost"] = _amount(values.get("SHIPPING"))
    row.fields["includes_taxes"] = False

    # Quantity -> pack_count (positive int).
    quantity = values.get("QUANTITY")
    pack = _parse_pack_count(quantity)
    if pack is None:
        row.fields["pack_count"] = 1
        if quantity not in (None, ""):
            row.warnings.append(f"non-integer quantity {quantity!r}; used 1")
    else:
        row.fields["pack_count"] = pack

    # Workflow dates.
    for column, model_field in _DATE_FIELDS.items():
        if column in values:
            parsed = parsers.parse_european_date(values[column])
            if parsed is None:
                row.warnings.append(f"unparseable {column}: {values[column]!r}")
            else:
                row.fields[model_field] = parsed

    # Relations resolved at commit time.
    row.vendor_name = _text(values, "SUPPLIER")
    row.budget_number = _text(values, "GRANT_ID")
    row.requested_by_email = _email(values, "REQUESTED_BY", row)
    row.approver_email = _email(values, "APPROVED_BY", row)

    item_type = _text(values, "ITEM_TYPE")
    if item_type:
        row.tag_names.append(item_type)

    row.fields["comment"] = _build_comment(values, extra_url=overflow_url)
    return row


def build_orders_plan(path: str | Path) -> OrderImportPlan:
    """Dry run: parse the whole orders workbook into a plan (no DB writes)."""
    plan = OrderImportPlan()
    for raw in orders.iter_rows(path):
        plan.rows.append(_parse_order(raw))
    return plan


@dataclass
class OrderImportResult:
    created: int = 0
    skipped: int = 0


def _cached(cache: dict, key: str, make):
    if key not in cache:
        cache[key] = make()
    return cache[key]


@transaction.atomic
def commit_orders(
    plan: OrderImportPlan, *, lab: Lab, actor: User | None = None
) -> OrderImportResult:
    """Persist the OK rows of a plan into ``lab`` as Requests, in one transaction.

    Vendors, budgets, tags and (stub) requester/approver users are resolved and cached
    per run. Rows with errors are skipped. Orders have no stable key, so every OK row is
    created — re-importing the same workbook duplicates rather than updates.
    """
    result = OrderImportResult()
    vendors: dict[str, Vendor] = {}
    budgets: dict[str, Budget] = {}
    users: dict[str, User] = {}
    tags: dict[str, Tag] = {}

    for row in plan.rows:
        if not row.ok:
            result.skipped += 1
            continue

        vendor = None
        if row.vendor_name:
            vendor = _cached(
                vendors,
                row.vendor_name,
                lambda n=row.vendor_name: Vendor.objects.get_or_create(lab=lab, name=n)[0],
            )
        budget = None
        if row.budget_number:
            budget = _cached(
                budgets,
                row.budget_number,
                lambda n=row.budget_number: Budget.objects.get_or_create(
                    lab=lab, number=n, defaults={"name": n}
                )[0],
            )

        def _user(email: str) -> User | None:
            if not email:
                return None
            return _cached(
                users,
                email,
                lambda e=email: User.objects.get_or_create(email=e, defaults={"username": e})[0],
            )

        request = Request.objects.create(
            lab=lab,
            vendor=vendor,
            budget=budget,
            requested_by=_user(row.requested_by_email),
            approver=_user(row.approver_email),
            **row.fields,
        )
        if row.tag_names:
            request.tags.set(
                _cached(tags, name, lambda n=name: Tag.objects.get_or_create(lab=lab, name=n)[0])
                for name in row.tag_names
            )
        result.created += 1

    AuditEntry.record(
        lab=lab,
        actor=actor,
        action="procurement.orders_imported",
        target=("Import", lab.pk),
        changes={"created": result.created, "skipped": result.skipped},
    )
    return result
