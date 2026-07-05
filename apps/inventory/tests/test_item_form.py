"""ItemForm behaviour: on-the-fly vendor/tag creation and form attachments."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.attachments.models import Attachment
from apps.inventory.forms import ItemForm
from apps.inventory.models import Item, Tag
from apps.procurement.models import Vendor
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab


@pytest.fixture
def lab(db):
    return create_lab(name="Form Lab", item_id_prefix="FL")


def _form_data(**overrides) -> dict:
    data = {"name": "Acetone", "tags": []}
    data.update(overrides)
    return data


def _save(form: ItemForm, lab) -> Item:
    """Mirror the view's create flow: the lab is assigned outside the form."""
    assert form.is_valid(), form.errors
    item = form.save(commit=False)
    item.lab = lab
    item.save()
    form.save_m2m()
    return item


def test_new_vendor_is_created_on_save(lab):
    form = ItemForm(_form_data(new_vendor="Carl Roth"), lab=lab)
    item = _save(form, lab)
    assert item.vendor == Vendor.objects.get(lab=lab, name="Carl Roth")


def test_new_vendor_reuses_existing_name(lab):
    existing = Vendor.objects.create(lab=lab, name="Carl Roth")
    form = ItemForm(_form_data(new_vendor="Carl Roth"), lab=lab)
    item = _save(form, lab)
    assert item.vendor == existing
    assert Vendor.objects.filter(lab=lab).count() == 1


def test_selected_vendor_wins_over_new_vendor(lab):
    chosen = Vendor.objects.create(lab=lab, name="Sigma")
    form = ItemForm(_form_data(vendor=chosen.pk, new_vendor="Carl Roth"), lab=lab)
    item = _save(form, lab)
    assert item.vendor == chosen
    assert not Vendor.objects.filter(lab=lab, name="Carl Roth").exists()


def test_item_without_any_vendor_is_valid(lab):
    # Unlike a request, an item does not need a vendor.
    form = ItemForm(_form_data(), lab=lab)
    item = _save(form, lab)
    assert item.vendor is None


def test_new_tags_are_created_and_attached(lab):
    existing = Tag.objects.create(lab=lab, name="solvent")
    form = ItemForm(
        _form_data(tags=[existing.pk], new_tags=["flammable", "2026", " flammable "]),
        lab=lab,
    )
    item = _save(form, lab)
    assert sorted(tag.name for tag in item.tags.all()) == ["2026", "flammable", "solvent"]


def test_new_tag_reuses_existing_row(lab):
    Tag.objects.create(lab=lab, name="solvent")
    form = ItemForm(_form_data(new_tags=["solvent"]), lab=lab)
    _save(form, lab)
    assert Tag.objects.filter(lab=lab).count() == 1


def test_overlong_new_tag_is_rejected(lab):
    form = ItemForm(_form_data(new_tags=["x" * 101]), lab=lab)
    assert not form.is_valid()


def test_attachments_uploaded_with_the_form_are_stored(lab, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    user = User.objects.create_user(username="", email="u@x.de", password="pw")
    files = {
        "attachments": [
            SimpleUploadedFile("sds.pdf", b"%PDF sds"),
            SimpleUploadedFile("coa.pdf", b"%PDF coa"),
        ]
    }
    form = ItemForm(_form_data(), files, lab=lab)
    item = _save(form, lab)
    form.save_attachments(user=user)
    names = sorted(a.original_name for a in Attachment.for_object(item))
    assert names == ["coa.pdf", "sds.pdf"]
    assert all(a.uploaded_by == user for a in Attachment.for_object(item))


def test_disallowed_form_attachment_is_a_validation_error(lab):
    form = ItemForm(_form_data(), {"attachments": [SimpleUploadedFile("run.exe", b"MZ")]}, lab=lab)
    assert not form.is_valid()
    assert "attachments" in form.errors


@pytest.fixture
def manager(lab):
    user = User.objects.create_user(username="", email="mgr@x.de", password="pw")
    add_member(user=user, lab=lab, role_names=["Lab manager"])
    return user


@pytest.mark.django_db
def test_create_view_stores_form_attachment(client, lab, manager, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    client.force_login(manager)
    resp = client.post(
        reverse("inventory:item_create"),
        {"name": "Acetone", "tags": [], "attachments": SimpleUploadedFile("sds.pdf", b"%PDF")},
    )
    assert resp.status_code == 302
    item = Item.objects.get(lab=lab, name="Acetone")
    assert [a.original_name for a in Attachment.for_object(item)] == ["sds.pdf"]


@pytest.mark.django_db
def test_create_page_renders_section_cards(client, lab, manager):
    client.force_login(manager)
    resp = client.get(reverse("inventory:item_create"))
    assert resp.status_code == 200
    for heading in (b"Storage &amp; ownership", b"Hazard data (GHS)", b"Vendor &amp; price"):
        assert heading in resp.content
    # The combobox/tag widgets need the hidden new_vendor input and the tag picker hook.
    assert b'name="new_vendor"' in resp.content
    assert b"data-tags" in resp.content
