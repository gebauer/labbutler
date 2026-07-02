"""Generic importer tests: column reading, mapping, plan building, and ID allocation.

The reading/plan-building layer is pure, so these build small synthetic workbooks and
assert the parsed result directly; the commit test checks that serial-less generic rows
get freshly allocated frozen IDs.
"""

from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from apps.imports import generic
from apps.imports.service import commit
from apps.inventory.models import Item
from apps.tenancy.services import create_lab


def _wb(tmp_path: Path, headers: list[str], rows: list[list], sheet: str = "Sheet1") -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    path = tmp_path / "generic.xlsx"
    workbook.save(path)
    return path


def test_read_columns_returns_headers_and_preview(tmp_path):
    path = _wb(tmp_path, ["Product", "CAS"], [["Ethanol", "64-17-5"], ["Water", ""]])
    cols = generic.read_columns(path)
    assert cols.headers == ["Product", "CAS"]
    assert cols.sheet == "Sheet1"
    assert cols.preview_rows[0] == ["Ethanol", "64-17-5"]


def test_guess_target_matches_common_headers():
    assert generic.guess_target("Product name") == "name"
    assert generic.guess_target("CAS No.") == "cas_number"
    assert generic.guess_target("Supplier") == "vendor"
    assert generic.guess_target("Storage location") == "location"
    assert generic.guess_target("Mystery") == generic.IGNORE


def test_validate_mapping_requires_a_name_column():
    assert generic.validate_mapping({"A": "ignore", "B": "cas_number"})  # non-empty errors
    assert generic.validate_mapping({"A": "name"}) == []


def test_build_generic_plan_applies_every_target_kind(tmp_path):
    path = _wb(
        tmp_path,
        ["Product", "Price", "Room", "Shelf", "Tags", "Supplier", "Owner", "Purity"],
        [
            [
                "Ethanol",
                "18,80 EUR",
                "Storage room (376)",
                "Fridge 2",
                "solvent, flammable",
                "Sigma",
                "alice@uni.de",
                "99%",
            ]
        ],
    )
    mapping = {
        "Product": "name",
        "Price": "price",
        "Room": "location",
        "Shelf": "location",
        "Tags": "tag",
        "Supplier": "vendor",
        "Owner": "owner",
        "Purity": "custom",
    }
    plan = generic.plan_from_file(path, "Sheet1", mapping)

    assert len(plan.rows) == 1
    row = plan.rows[0]
    assert row.ok
    assert row.fields["name"] == "Ethanol"
    assert row.fields["price_amount"] == Decimal("18.80")
    assert row.fields["price_currency"] == "EUR"
    # Two columns mapped to location build a hierarchy in column order.
    assert [level.name for level in row.location_path] == ["Storage room", "Fridge 2"]
    assert set(row.tag_names) == {"solvent", "flammable"}
    assert row.vendor_name == "Sigma"
    assert row.owner_email == "alice@uni.de"
    assert row.custom_fields["purity"] == "99%"
    assert ("purity", "Purity") in row.field_pool_keys
    # Generic rows carry no human_id; commit mints one.
    assert row.human_id == ""


def test_row_missing_name_is_an_error(tmp_path):
    path = _wb(tmp_path, ["Product", "CAS"], [["", "64-17-5"]])
    plan = generic.plan_from_file(path, "Sheet1", {"Product": "name", "CAS": "cas_number"})
    assert not plan.rows[0].ok
    assert "missing name" in plan.rows[0].errors


@pytest.mark.django_db
def test_commit_allocates_fresh_frozen_ids_for_generic_rows(tmp_path):
    lab = create_lab(name="Gen Lab", item_id_prefix="GEN")
    path = _wb(tmp_path, ["Product"], [["Ethanol"], ["Water"]])
    plan = generic.plan_from_file(path, "Sheet1", {"Product": "name"})

    result = commit(plan, lab=lab)

    assert result.created == 2
    ids = set(Item.objects.filter(lab=lab).values_list("human_id", flat=True))
    assert ids == {"GEN-00001", "GEN-00002"}


def test_plan_refuses_more_rows_than_the_cap():
    rows = ({"Product": f"Item {i}"} for i in range(10))
    with pytest.raises(generic.ImportTooLarge):
        generic.build_generic_plan(rows, {"Product": "name"}, max_rows=5)


def test_plan_accepts_exactly_the_cap():
    rows = ({"Product": f"Item {i}"} for i in range(5))
    plan = generic.build_generic_plan(rows, {"Product": "name"}, max_rows=5)
    assert len(plan.rows) == 5
