"""RequestForm behaviour: lab defaults, on-the-fly vendor/tag creation."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.inventory.models import Tag
from apps.procurement.forms import RequestForm
from apps.procurement.models import Budget, Request, ShippingAddress, Vendor
from apps.tenancy.services import create_lab


@pytest.fixture
def lab(db):
    return create_lab(name="Form Lab", item_id_prefix="FL")


def _form_data(lab, **overrides) -> dict:
    """Minimal valid payload; vendor and budget are required, so defaults are created."""
    vendor, _ = Vendor.objects.get_or_create(lab=lab, name="ACME Supplies")
    budget, _ = Budget.objects.get_or_create(lab=lab, number="KST-0", defaults={"name": "Core"})
    data = {
        "item_name": "Pipette tips",
        "vendor": str(vendor.pk),
        "budget": str(budget.pk),
        "unit_price": "10.00",
        "currency": "EUR",
        "pack_count": "2",
        "shipping_cost": "0",
    }
    data.update(overrides)
    return data


def _save(form: RequestForm) -> Request:
    assert form.is_valid(), form.errors
    return form.save()


def test_currency_defaults_to_lab_currency(lab):
    lab.default_currency = "CHF"
    lab.save()
    form = RequestForm(lab=lab)
    assert form.get_initial_for_field(form.fields["currency"], "currency") == "CHF"


def test_currency_falls_back_to_eur(lab):
    lab.default_currency = ""
    lab.save()
    form = RequestForm(lab=lab)
    assert form.get_initial_for_field(form.fields["currency"], "currency") == "EUR"


def test_expected_delivery_defaults_to_one_week(lab):
    form = RequestForm(lab=lab)
    assert form.initial["expected_delivery"] == date.today() + timedelta(weeks=1)


def test_forward_to_offers_only_accept_forwards_holders(lab):
    from apps.tenancy.models import User
    from apps.tenancy.services import add_member

    coord = User.objects.create_user(username="", email="coord@x.de", password="pw")
    add_member(user=coord, lab=lab, role_names=["Purchase coordinator"])
    member = User.objects.create_user(username="", email="member@x.de", password="pw")
    add_member(user=member, lab=lab, role_names=["Member"])

    form = RequestForm(lab=lab)
    assert list(form.fields["forward_to"].queryset) == [coord]
    assert form.fields["forward_to"].required is False

    req = _save(RequestForm(_form_data(lab, forward_to=str(coord.pk)), lab=lab))
    assert req.forward_to == coord
    assert req.assigned_to is None  # hand-over only happens at approval


def test_editing_keeps_the_stored_expected_delivery(lab):
    req = Request.objects.create(lab=lab, item_name="X", expected_delivery=date(2026, 8, 1))
    form = RequestForm(instance=req, lab=lab)
    assert form.initial["expected_delivery"] == date(2026, 8, 1)


def test_default_shipping_address_is_preselected(lab):
    ShippingAddress.objects.create(lab=lab, label="Loading dock", address="Back door")
    main = ShippingAddress.objects.create(
        lab=lab, label="Main office", address="Front desk", is_default=True
    )
    form = RequestForm(lab=lab)
    assert form.initial["shipping_address"] == main


def test_only_address_is_preselected_without_explicit_default(lab):
    only = ShippingAddress.objects.create(lab=lab, label="Main office", address="Front desk")
    form = RequestForm(lab=lab)
    assert form.initial["shipping_address"] == only


def test_no_preselection_with_several_addresses_and_no_default(lab):
    ShippingAddress.objects.create(lab=lab, label="A", address="a")
    ShippingAddress.objects.create(lab=lab, label="B", address="b")
    form = RequestForm(lab=lab)
    assert "shipping_address" not in form.initial


def test_default_budget_is_preselected(lab):
    Budget.objects.create(lab=lab, number="KST-1", name="Other grant")
    core = Budget.objects.create(lab=lab, number="KST-2", name="Core grant", is_default=True)
    form = RequestForm(lab=lab)
    assert form.initial["budget"] == core


def test_only_budget_is_preselected_without_explicit_default(lab):
    only = Budget.objects.create(lab=lab, number="KST-1", name="Core grant")
    form = RequestForm(lab=lab)
    assert form.initial["budget"] == only


def test_new_default_budget_demotes_previous_default(lab):
    old = Budget.objects.create(lab=lab, number="KST-1", name="Old", is_default=True)
    Budget.objects.create(lab=lab, number="KST-2", name="New", is_default=True)
    old.refresh_from_db()
    assert not old.is_default


def test_new_default_address_demotes_previous_default(lab):
    old = ShippingAddress.objects.create(lab=lab, label="Old", address="o", is_default=True)
    ShippingAddress.objects.create(lab=lab, label="New", address="n", is_default=True)
    old.refresh_from_db()
    assert not old.is_default


def test_new_vendor_is_created_on_save(lab):
    form = RequestForm(_form_data(lab, vendor="", new_vendor="Carl Roth"), lab=lab)
    req = _save(form)
    assert req.vendor == Vendor.objects.get(lab=lab, name="Carl Roth")


def test_new_vendor_reuses_existing_name(lab):
    existing = Vendor.objects.create(lab=lab, name="Carl Roth")
    form = RequestForm(_form_data(lab, vendor="", new_vendor="Carl Roth"), lab=lab)
    req = _save(form)
    assert req.vendor == existing
    assert Vendor.objects.filter(lab=lab, name="Carl Roth").count() == 1


def test_new_vendor_reuses_case_and_whitespace_variants(lab):
    existing = Vendor.objects.create(lab=lab, name="Carl Roth")
    form = RequestForm(_form_data(lab, vendor="", new_vendor="  carl  ROTH "), lab=lab)
    req = _save(form)
    assert req.vendor == existing
    assert Vendor.objects.filter(lab=lab, name__iexact="carl roth").count() == 1


def test_selected_vendor_wins_over_new_vendor(lab):
    chosen = Vendor.objects.create(lab=lab, name="Sigma")
    form = RequestForm(_form_data(lab, vendor=chosen.pk, new_vendor="Carl Roth"), lab=lab)
    req = _save(form)
    assert req.vendor == chosen
    assert not Vendor.objects.filter(lab=lab, name="Carl Roth").exists()


def test_vendor_is_required_without_a_new_vendor_name(lab):
    form = RequestForm(_form_data(lab, vendor="", new_vendor="  "), lab=lab)
    assert not form.is_valid()
    assert "vendor" in form.errors


def test_budget_is_required(lab):
    form = RequestForm(_form_data(lab, budget=""), lab=lab)
    assert not form.is_valid()
    assert "budget" in form.errors


def test_zero_price_is_valid_server_side(lab):
    """0 stays allowed (free samples); the UI asks for confirmation instead."""
    form = RequestForm(_form_data(lab, unit_price="0"), lab=lab)
    assert form.is_valid(), form.errors


def test_new_tags_are_created_and_attached(lab):
    existing = Tag.objects.create(lab=lab, name="antibody")
    form = RequestForm(
        _form_data(lab, tags=[existing.pk], new_tags=["urgent-order", "2026", " urgent-order "]),
        lab=lab,
    )
    req = _save(form)
    assert sorted(tag.name for tag in req.tags.all()) == ["2026", "antibody", "urgent-order"]


def test_new_tag_reuses_existing_row(lab):
    Tag.objects.create(lab=lab, name="antibody")
    form = RequestForm(_form_data(lab, new_tags=["antibody"]), lab=lab)
    _save(form)
    assert Tag.objects.filter(lab=lab).count() == 1


def test_overlong_new_tag_is_rejected(lab):
    form = RequestForm(_form_data(lab, new_tags=["x" * 101]), lab=lab)
    assert not form.is_valid()


def test_exotic_currency_on_existing_request_stays_selectable(lab):
    req = Request.objects.create(lab=lab, item_name="Old import", currency="SEK")
    form = RequestForm(instance=req, lab=lab)
    assert ("SEK", "SEK") in form.fields["currency"].choices


def test_attachments_uploaded_with_the_form_are_stored(lab, settings, tmp_path):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.attachments.models import Attachment
    from apps.tenancy.models import User

    settings.MEDIA_ROOT = str(tmp_path / "media")
    user = User.objects.create_user(username="", email="u@x.de", password="pw")
    files = {
        "attachments": [
            SimpleUploadedFile("po.pdf", b"%PDF po"),
            SimpleUploadedFile("sds.pdf", b"%PDF sds"),
        ]
    }
    form = RequestForm(_form_data(lab), files, lab=lab)
    req = _save(form)
    form.save_attachments(user=user)
    names = sorted(a.original_name for a in Attachment.for_object(req))
    assert names == ["po.pdf", "sds.pdf"]
    assert all(a.uploaded_by == user for a in Attachment.for_object(req))


def test_disallowed_form_attachment_is_a_validation_error(lab):
    from django.core.files.uploadedfile import SimpleUploadedFile

    form = RequestForm(
        _form_data(lab), {"attachments": [SimpleUploadedFile("run.exe", b"MZ")]}, lab=lab
    )
    assert not form.is_valid()
    assert "attachments" in form.errors


def test_hazard_data_is_saved(lab):
    form = RequestForm(
        _form_data(lab, signal_word="danger", storage_class="8A", hazards=["H225", "P210"]),
        lab=lab,
    )
    req = _save(form)
    assert req.signal_word == "danger"
    assert req.storage_class == "8A"
    assert sorted(h.code for h in req.hazards.all()) == ["H225", "P210"]


def test_hazard_data_is_optional(lab):
    req = _save(RequestForm(_form_data(lab), lab=lab))
    assert req.signal_word == ""
    assert not req.hazards.exists()


def test_unknown_hazard_code_is_rejected(lab):
    form = RequestForm(_form_data(lab, hazards=["H999"]), lab=lab)
    assert not form.is_valid()
    assert "hazards" in form.errors


def test_save_recalculates_nothing_but_view_does(lab):
    """The form itself leaves tax/total at defaults; the view recalculates before save."""
    form = RequestForm(_form_data(lab, unit_price="100.00", pack_count="1"), lab=lab)
    req = _save(form)
    req.recalculate_totals()
    assert req.total == Decimal("119.00")
