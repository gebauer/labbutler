"""LabSuit orders importer tests.

The end-to-end tests run against the real orders export in ``sample_data/`` when it is
present (git-ignored, so CI without it skips them). The synthetic-workbook tests always
run and cover status/date/money mapping and relation creation deterministically.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from apps.imports.orders_service import build_orders_plan, commit_orders
from apps.procurement.models import Budget, Request, Vendor
from apps.tenancy.models import User
from apps.tenancy.services import create_lab

SAMPLE = Path(__file__).resolve().parents[3] / "sample_data" / "AG Baumann-orders-02-07-2026.xlsx"

# The full LabSuit orders column layout.
HEADER = [
    "ITEM_NAME",
    "CAS_NUMBER",
    "CATALOG_NUMBER",
    "MANUFACTURER",
    "SUPPLIER",
    "ITEM_TYPE",
    "COMMENTS",
    "GRANT_ID",
    "REQUESTED_BY",
    "QUOTE_ID",
    "PURCHASE_ORDER_NUMBER",
    "REQUISITION_NUMBER",
    "CONFIRMATION_NUMBER",
    "TRACKING_NUMBER",
    "INVOICE_NUMBER",
    "STATUS",
    "PACK_SIZE",
    "QUANTITY",
    "CURRENCY",
    "PRICE",
    "TAX",
    "TOTAL",
    "URL",
    "SHIPPING",
    "DATE_REQUESTED",
    "DATE_APPROVED",
    "DATE_ORDERED",
    "DATE_CANCELLED",
    "DATE_RECEIVED",
    "APPROVED_BY",
    "ORDERED_BY",
    "CANCELLED_BY",
    "RECEIVED_BY",
    "APPROVED_MESSAGE",
    "ORDERED_MESSAGE",
    "CANCELLED_MESSAGE",
    "RECEIVED_MESSAGE",
]


def _row(**overrides) -> list:
    values = {h: "" for h in HEADER}
    values.update(overrides)
    return [values[h] for h in HEADER]


def _make_workbook(tmp_path: Path, rows: list[list], sheet: str = "Year - 2026") -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(HEADER)
    for row in rows:
        ws.append(row)
    path = tmp_path / "orders.xlsx"
    wb.save(path)
    return path


def test_build_plan_maps_status_dates_and_money(tmp_path):
    path = _make_workbook(
        tmp_path,
        [
            _row(
                ITEM_NAME="Ablaufpumpe",
                CATALOG_NUMBER="7035135",
                SUPPLIER="Gastroteileshop",
                ITEM_TYPE="Ersatzteile",
                GRANT_ID="154005003",
                REQUESTED_BY="a@uni-koeln.de",
                APPROVED_BY="b@uni-koeln.de",
                STATUS="received",
                QUANTITY="1",
                CURRENCY="EUR",
                PRICE="188.00",
                TAX="37.25",
                TOTAL="EUR 225.25",
                SHIPPING="7.05",
                DATE_REQUESTED="17-06-2026",
                DATE_RECEIVED="02-07-2026",
                PURCHASE_ORDER_NUMBER="391238",
                COMMENTS="Ersatzteil",
            ),
        ],
    )
    plan = build_orders_plan(path)

    assert plan.counts() == {"ok": 1, "warnings": 0, "errors": 0}
    row = plan.rows[0]
    assert row.fields["item_name"] == "Ablaufpumpe"
    assert row.fields["status"] == Request.Status.CHECKED_IN  # received -> checked in
    assert row.fields["unit_price"] == Decimal("188.00")
    assert row.fields["tax"] == Decimal("37.25")
    assert row.fields["total"] == Decimal("225.25")  # preserved verbatim, not recomputed
    assert row.fields["shipping_cost"] == Decimal("7.05")
    assert row.fields["date_requested"] == date(2026, 6, 17)
    assert row.fields["date_received"] == date(2026, 7, 2)
    assert row.vendor_name == "Gastroteileshop"
    assert row.budget_number == "154005003"
    assert row.requested_by_email == "a@uni-koeln.de"
    assert row.approver_email == "b@uni-koeln.de"
    assert row.tag_names == ["Ersatzteile"]
    assert row.fields["po_number"] == "391238"
    assert "Type: Ersatzteile" in row.fields["comment"]  # unmapped field folded in


def test_missing_name_is_error_and_bad_values_warn(tmp_path):
    path = _make_workbook(
        tmp_path,
        [
            _row(ITEM_NAME="", STATUS="received"),  # error: no name
            _row(ITEM_NAME="Widget", STATUS="teleported", QUANTITY="a few"),  # two warnings
        ],
    )
    plan = build_orders_plan(path)

    assert plan.counts() == {"ok": 1, "warnings": 1, "errors": 1}
    assert plan.rows[0].errors
    good = plan.rows[1]
    assert good.fields["status"] == Request.Status.REQUESTED  # unknown -> requested
    assert good.fields["pack_count"] == 1  # bad quantity -> 1
    assert len(good.warnings) == 2


@pytest.mark.django_db
def test_commit_creates_requests_relations_and_dates(tmp_path):
    lab = create_lab(name="AG Baumann", item_id_prefix="AGB")
    path = _make_workbook(
        tmp_path,
        [
            _row(
                ITEM_NAME="Oligo",
                SUPPLIER="Merck",
                ITEM_TYPE="Oligo",
                GRANT_ID="154005003",
                REQUESTED_BY="jan@uni-koeln.de",
                APPROVED_BY="uli@uni-koeln.de",
                STATUS="approved",
                QUANTITY="2",
                CURRENCY="EUR",
                PRICE="6.38",
                TAX="1.21",
                TOTAL="EUR 7.59",
                DATE_REQUESTED="01-07-2026",
                DATE_APPROVED="01-07-2026",
            ),
        ],
    )
    result = commit_orders(build_orders_plan(path), lab=lab)

    assert result.created == 1
    req = Request.objects.get(lab=lab, item_name="Oligo")
    assert req.status == Request.Status.APPROVED
    assert req.pack_count == 2
    assert req.total == Decimal("7.59")
    assert req.date_approved == date(2026, 7, 1)
    assert req.vendor == Vendor.objects.get(lab=lab, name="Merck")
    assert req.budget == Budget.objects.get(lab=lab, number="154005003")
    assert req.requested_by.email == "jan@uni-koeln.de"
    assert req.approver.email == "uli@uni-koeln.de"
    assert set(req.tags.values_list("name", flat=True)) == {"Oligo"}


@pytest.mark.django_db
def test_commit_reuses_relations_across_rows(tmp_path):
    lab = create_lab(name="Reuse Lab", item_id_prefix="RL")
    path = _make_workbook(
        tmp_path,
        [
            _row(ITEM_NAME="A", SUPPLIER="Merck", GRANT_ID="G1", REQUESTED_BY="x@lab.de"),
            _row(ITEM_NAME="B", SUPPLIER="Merck", GRANT_ID="G1", REQUESTED_BY="x@lab.de"),
        ],
    )
    result = commit_orders(build_orders_plan(path), lab=lab)

    assert result.created == 2
    assert Vendor.objects.filter(lab=lab).count() == 1
    assert Budget.objects.filter(lab=lab).count() == 1
    assert User.objects.filter(email="x@lab.de").count() == 1


@pytest.mark.django_db
def test_commit_aligns_timestamps_to_workflow_dates(tmp_path):
    lab = create_lab(name="Timestamp Lab", item_id_prefix="TS")
    path = _make_workbook(
        tmp_path,
        [
            _row(
                ITEM_NAME="Old order",
                STATUS="received",
                DATE_REQUESTED="05-06-2019",
                DATE_RECEIVED="10-08-2023",
            ),
            _row(ITEM_NAME="No dates", STATUS="requested"),
        ],
    )
    commit_orders(build_orders_plan(path), lab=lab)

    dated = Request.objects.get(lab=lab, item_name="Old order")
    assert dated.created_at.date() == date(2019, 6, 5)  # requested date -> created
    assert dated.updated_at.date() == date(2023, 8, 10)  # latest milestone -> updated
    # A request with no historical dates keeps its real (import-time) timestamp.
    undated = Request.objects.get(lab=lab, item_name="No dates")
    assert undated.created_at.date() == date.today()


# --- Real sample (skipped when the git-ignored file is absent) ------------------------


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample_data orders export not present")
def test_real_orders_dry_run_has_no_errors():
    plan = build_orders_plan(SAMPLE)
    counts = plan.counts()
    assert counts["ok"] > 2000
    # The only expected errors are genuine blank draft rows (no ITEM_NAME); any other
    # error means a parsing regression.
    unexpected = [
        (r.sheet, r.row_number, r.errors)
        for r in plan.rows
        if r.errors and r.errors != ["missing ITEM_NAME"]
    ]
    assert not unexpected, unexpected[:10]


@pytest.mark.django_db
@pytest.mark.skipif(not SAMPLE.exists(), reason="sample_data orders export not present")
@pytest.mark.slow
def test_real_orders_commit():
    lab = create_lab(name="AG Baumann", item_id_prefix="AGB")
    plan = build_orders_plan(SAMPLE)
    result = commit_orders(plan, lab=lab)
    assert result.created > 2000
    assert Request.objects.filter(lab=lab).count() == result.created
