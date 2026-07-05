"""Importer tests.

The end-to-end tests run against the real LabSuit export in ``sample_data/`` when it is
present (it is git-ignored, so CI without it skips those tests). The synthetic workbook
tests always run and cover the dedup/hierarchy/hazard behaviour deterministically.
"""

from pathlib import Path

import openpyxl
import pytest

from apps.imports.service import build_plan, commit
from apps.inventory.models import HazardStatement, Item, Location
from apps.procurement.models import Vendor
from apps.tenancy.services import create_lab

SAMPLE = (
    Path(__file__).resolve().parents[3] / "sample_data" / "AG Baumann-inventory-30-06-2026.xlsx"
)

# Core LabSuit columns a minimal synthetic sheet needs.
HEADER = [
    "Delete? (y/n)",
    "SERIAL_NUMBER",
    "NAME",
    "TAGS",
    "AMOUNT_IN_STOCK",
    "LOCATION",
    "SUB_LOCATION",
    "SUPPLIER",
    "PRICE",
    "EXPIRATION_DATE",
    "CAS_NUMBER",
    "OWNER",
    "PURITY",
]


def _make_workbook(tmp_path: Path, sheet: str, rows: list[list]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(HEADER)
    for row in rows:
        ws.append(row)
    path = tmp_path / "export.xlsx"
    wb.save(path)
    return path


def test_build_plan_resolves_fields_and_summary(tmp_path):
    path = _make_workbook(
        tmp_path,
        "Chemical",
        [
            [
                "",
                "ch-0005",
                "CHAPS",
                "Achtung,H319,WGK 1,LK 6.1D,2022",
                "1",
                "Storage room (376)",
                "Fridge 2",
                "Sigma",
                "18.80EUR",
                "",
                "75621-03-3",
                "alice@uni-koeln.de",
                "99%",
            ],
            ["", "", "No serial", "", "1", "", "", "", "", "", "", "", ""],
        ],
    )
    plan = build_plan(path)

    assert len(plan.rows) == 2
    good = plan.rows[0]
    assert good.ok
    assert good.human_id == "ch-0005"
    assert good.fields["price_amount"] is not None
    assert good.hazard_codes == ["H319"]
    assert good.fields["signal_word"] == "warning"
    assert "Chemical" in good.tag_names  # sheet name becomes a tag
    assert good.custom_fields["purity"] == "99%"
    # Second row has no serial -> an error row.
    assert plan.rows[1].errors
    assert plan.counts()["errors"] == 1


@pytest.mark.django_db
def test_commit_creates_items_hierarchy_and_relations(tmp_path):
    lab = create_lab(name="AG Baumann", item_id_prefix="AGB")
    path = _make_workbook(
        tmp_path,
        "Chemical",
        [
            [
                "",
                "ch-0005",
                "CHAPS",
                "Gefahr,H319,H315",
                "1",
                "Storage room (376)",
                "Fridge 2",
                "Sigma",
                "18.80EUR",
                "02-01-2027",
                "75621-03-3",
                "alice@uni-koeln.de",
                "99%",
            ],
        ],
    )
    plan = build_plan(path)
    result = commit(plan, lab=lab)

    assert result.created == 1
    item = Item.objects.get(lab=lab, human_id="ch-0005")
    assert item.name == "CHAPS"
    assert item.signal_word == "danger"
    assert set(item.hazards.values_list("code", flat=True)) == {"H319", "H315"}
    assert item.vendor == Vendor.objects.get(lab=lab, name="Sigma")
    assert item.owner.email == "alice@uni-koeln.de"
    # Location hierarchy: Storage room (376) -> Fridge 2.
    assert item.location.name == "Fridge 2"
    assert item.location.parent.name == "Storage room"
    assert item.location.parent.room_number == "376"
    # Extra column registered in the custom-field pool.
    assert lab.field_definitions.filter(key="purity").exists()
    # Hazard catalog populated with correct kinds.
    assert HazardStatement.objects.get(code="H319").kind == "H"


@pytest.mark.django_db
def test_commit_is_idempotent_on_reimport(tmp_path):
    lab = create_lab(name="Re Lab", item_id_prefix="RL")
    rows = [["", "ch-1", "Item one", "", "1", "Room 10", "", "", "", "", "", "", ""]]
    path = _make_workbook(tmp_path, "Chemical", rows)

    first = commit(build_plan(path), lab=lab)
    second = commit(build_plan(path), lab=lab)

    assert first.created == 1
    assert second.created == 0 and second.updated == 1
    assert Item.objects.filter(lab=lab).count() == 1
    assert Location.objects.filter(lab=lab).count() == 1  # no duplicate locations


def test_duplicate_serial_disambiguated(tmp_path):
    path = _make_workbook(
        tmp_path,
        "Chemical",
        [
            ["", "co-0001", "First", "", "1", "", "", "", "", "", "", "", ""],
            ["", "co-0001", "Second", "", "1", "", "", "", "", "", "", "", ""],
        ],
    )
    plan = build_plan(path)
    assert plan.rows[0].human_id == "co-0001"
    assert plan.rows[1].human_id == "co-0001#2"
    assert plan.rows[1].warnings


# --- Real sample (skipped when the git-ignored file is absent) ------------------------


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample_data export not present")
def test_real_export_dry_run_has_no_errors():
    plan = build_plan(SAMPLE)
    counts = plan.counts()
    # The real file should parse into a substantial number of items.
    assert counts["ok"] > 1500
    # No row should be a hard error (missing serial/name) in the real export.
    assert counts["errors"] == 0, [
        (r.sheet, r.row_number, r.errors) for r in plan.rows if r.errors
    ][:10]


@pytest.mark.django_db
@pytest.mark.skipif(not SAMPLE.exists(), reason="sample_data export not present")
@pytest.mark.slow
def test_real_export_commits():
    lab = create_lab(name="AG Baumann", item_id_prefix="AGB")
    plan = build_plan(SAMPLE)
    result = commit(plan, lab=lab)
    assert result.created > 1500
    assert Item.objects.filter(lab=lab).count() == result.created
