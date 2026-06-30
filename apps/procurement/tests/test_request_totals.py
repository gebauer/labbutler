from decimal import Decimal

import pytest

from apps.procurement.models import Request
from apps.tenancy.services import create_lab


@pytest.mark.django_db
def test_total_adds_vat_when_taxes_not_included():
    lab = create_lab(name="VAT Lab", item_id_prefix="VL")  # default_vat_rate = 0.19
    req = Request(
        lab=lab,
        item_name="Pipette tips",
        unit_price=Decimal("100.00"),
        pack_count=2,
        shipping_cost=Decimal("10.00"),
        includes_taxes=False,
    )
    req.recalculate_totals()
    # subtotal = 100*2 + 10 = 210; tax = 210*0.19 = 39.90; total = 249.90
    assert req.tax == Decimal("39.90")
    assert req.total == Decimal("249.90")


@pytest.mark.django_db
def test_gross_price_keeps_total_and_back_calculates_tax():
    lab = create_lab(name="Gross Lab", item_id_prefix="GL")
    req = Request(
        lab=lab,
        item_name="Reagent",
        unit_price=Decimal("119.00"),
        pack_count=1,
        shipping_cost=Decimal("0.00"),
        includes_taxes=True,
    )
    req.recalculate_totals()
    # total taken as-is; tax = 119 - 119/1.19 = 19.00
    assert req.total == Decimal("119.00")
    assert req.tax.quantize(Decimal("0.01")) == Decimal("19.00")
