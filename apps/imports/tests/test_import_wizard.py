"""Import wizard tests: the upload -> map -> preview -> commit flow and its gating.

These drive the real views through the test client (session state carries between steps)
against an isolated MEDIA_ROOT so uploads land in a tmp dir.
"""

import io

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.inventory.models import Item
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


@pytest.fixture(autouse=True)
def isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")


def _member(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


def _upload(headers: list[str], rows: list[list]) -> SimpleUploadedFile:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active  # default title "Sheet"
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile("items.xlsx", buffer.getvalue(), content_type=XLSX_CONTENT_TYPE)


@pytest.mark.django_db
def test_full_wizard_creates_items(client, lab):
    client.force_login(_member(lab, "mgr@x.de", ["Lab manager"]))

    resp = client.post(
        reverse("imports:start"),
        {"spreadsheet": _upload(["Product", "CAS"], [["Ethanol", "64-17-5"], ["Water", ""]])},
    )
    assert resp.status_code == 302

    page = client.get(reverse("imports:mapping"))
    assert page.status_code == 200
    assert b"Product" in page.content

    resp = client.post(
        reverse("imports:mapping"),
        {"sheet": "Sheet", "col-0": "name", "col-1": "cas_number"},
    )
    assert resp.status_code == 302

    preview = client.get(reverse("imports:preview"))
    assert preview.status_code == 200
    assert b"Ethanol" in preview.content

    resp = client.post(reverse("imports:preview"))
    assert resp.status_code == 302
    names = set(Item.objects.filter(lab=lab).values_list("name", flat=True))
    assert names == {"Ethanol", "Water"}
    assert Item.objects.filter(lab=lab, name="Ethanol").first().human_id.startswith("AGB-")


@pytest.mark.django_db
def test_mapping_without_name_is_rejected(client, lab):
    client.force_login(_member(lab, "mgr@x.de", ["Lab manager"]))
    client.post(reverse("imports:start"), {"spreadsheet": _upload(["Product"], [["Ethanol"]])})

    resp = client.post(reverse("imports:mapping"), {"sheet": "Sheet", "col-0": "ignore"})

    assert resp.status_code == 200
    assert b"every item needs a name" in resp.content
    assert not Item.objects.filter(lab=lab).exists()


@pytest.mark.django_db
def test_start_forbidden_without_import_permission(client, lab):
    client.force_login(_member(lab, "view@x.de", ["Viewer"]))
    resp = client.get(reverse("imports:start"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_non_spreadsheet_upload_is_rejected(client, lab):
    client.force_login(_member(lab, "mgr@x.de", ["Lab manager"]))
    bad = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
    resp = client.post(reverse("imports:start"), {"spreadsheet": bad}, follow=True)
    assert b".xlsx" in resp.content  # error message shown
    assert "import_file" not in client.session
