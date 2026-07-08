"""Suggestion-engine tests: route nudges, PO-refresh nudges, and config resolution."""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.procurement import suggestions
from apps.procurement.models import PurchaseOrder, Request, Vendor
from apps.tenancy.services import create_lab

Route = Request.Route


@pytest.fixture
def lab(db):
    return create_lab(name="Suggest Lab", item_id_prefix="LB")


@pytest.fixture
def _tmp_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")


def _request(lab, *, net, vendor=None, includes_taxes=False, unit_price=None) -> Request:
    req = Request.objects.create(
        lab=lab,
        item_name="Zentrifuge",
        unit_price=unit_price if unit_price is not None else Decimal(net),
        includes_taxes=includes_taxes,
        vendor=vendor,
    )
    req.recalculate_totals()
    req.save()
    return req


@pytest.mark.django_db
def test_small_eu_order_suggests_direct(lab):
    vendor = Vendor.objects.create(lab=lab, name="Roth", country="DE")
    suggestion = suggestions.suggest_route(_request(lab, net="200.00", vendor=vendor))
    assert suggestion.route == Route.DIRECT
    assert suggestion.reasons == ()


@pytest.mark.django_db
def test_net_above_threshold_suggests_central_with_reason(lab):
    suggestion = suggestions.suggest_route(_request(lab, net="1500.00"))
    assert suggestion.route == Route.CENTRAL
    assert any("1500.00" in reason and "1000" in reason for reason in suggestion.reasons)


@pytest.mark.django_db
def test_non_eu_vendor_suggests_central_below_threshold(lab):
    vendor = Vendor.objects.create(lab=lab, name="NEB", country="US")
    suggestion = suggestions.suggest_route(_request(lab, net="200.00", vendor=vendor))
    assert suggestion.route == Route.CENTRAL
    assert any("US" in reason for reason in suggestion.reasons)


@pytest.mark.django_db
def test_unknown_vendor_country_contributes_no_signal(lab):
    vendor = Vendor.objects.create(lab=lab, name="Mystery Supplies")  # no country
    suggestion = suggestions.suggest_route(_request(lab, net="800.00", vendor=vendor))
    assert suggestion.route == Route.DIRECT
    assert suggestion.reasons == ()


@pytest.mark.django_db
def test_basis_is_net_so_gross_entry_cannot_flip_the_suggestion(lab):
    # 1100 € gross at 19% VAT is ~924 € net — below the 1000 € threshold.
    req = _request(lab, net="", unit_price=Decimal("1100.00"), includes_taxes=True)
    assert req.net_total < Decimal("1000")
    assert suggestions.suggest_route(req).route == Route.DIRECT


@pytest.mark.django_db
def test_lab_threshold_override_beats_instance_default(lab):
    lab.central_purchasing_threshold_net = Decimal("100.00")
    lab.save()
    suggestion = suggestions.suggest_route(_request(lab, net="200.00"))
    assert suggestion.route == Route.CENTRAL


def _po(lab, req, snapshot) -> PurchaseOrder:
    return PurchaseOrder.objects.create(
        request=req,
        po_snapshot_net=Decimal(snapshot),
        unsigned_pdf=SimpleUploadedFile("form.pdf", b"%PDF-1.4", content_type="application/pdf"),
    )


@pytest.mark.django_db
def test_po_refresh_nudges_above_deviation_threshold(lab, _tmp_media):
    po = _po(lab, _request(lab, net="1180.00"), "1000.00")
    result = suggestions.suggest_po_refresh(po, Decimal("1180.00"))
    assert result.should_refresh
    assert result.deviation_pct == Decimal("18.0")


@pytest.mark.django_db
def test_po_refresh_stays_quiet_below_threshold(lab, _tmp_media):
    po = _po(lab, _request(lab, net="1080.00"), "1000.00")
    result = suggestions.suggest_po_refresh(po, Decimal("1080.00"))
    assert not result.should_refresh
    assert result.deviation_pct == Decimal("8.0")


@pytest.mark.django_db
def test_po_refresh_lab_override(lab, _tmp_media):
    lab.po_deviation_threshold_pct = Decimal("5.00")
    lab.save()
    po = _po(lab, _request(lab, net="1080.00"), "1000.00")
    assert suggestions.suggest_po_refresh(po, Decimal("1080.00")).should_refresh
