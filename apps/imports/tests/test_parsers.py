from datetime import date
from decimal import Decimal

import pytest

from apps.imports.parsers import (
    parse_amount_in_stock,
    parse_european_date,
    parse_location_part,
    parse_location_path,
    parse_price,
    parse_tags,
)


@pytest.mark.parametrize(
    "raw,amount,currency",
    [
        ("235", Decimal("235"), ""),
        ("18.80EUR", Decimal("18.80"), "EUR"),
        ("EUR 109.00", Decimal("109.00"), "EUR"),
        ("110.00USD", Decimal("110.00"), "USD"),
        ("$ 500.00", Decimal("500.00"), "USD"),
        ("EUR 1,249.00", Decimal("1249.00"), "EUR"),
        ("500 $", Decimal("500"), "USD"),
        ("Money(109.00,EUR)", Decimal("109.00"), "EUR"),
    ],
)
def test_parse_price(raw, amount, currency):
    parsed = parse_price(raw)
    assert parsed.amount == amount
    assert parsed.currency == currency


def test_parse_price_european_comma_decimal():
    assert parse_price("18,80EUR").amount == Decimal("18.80")


def test_parse_price_blank_and_junk():
    assert parse_price("").amount is None
    assert parse_price(None).amount is None
    bad = parse_price("on request")
    assert bad.amount is None and bad.warning


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("02-01-2017", date(2017, 1, 2)),
        ("28-06-2017", date(2017, 6, 28)),
        ("5.3.2020", date(2020, 3, 5)),
        ("", None),
        ("not a date", None),
        ("31-02-2020", None),  # invalid day for month
    ],
)
def test_parse_european_date(raw, expected):
    assert parse_european_date(raw) == expected


def test_parse_location_paren_and_room_number():
    level = parse_location_part("Storage room (376)")
    assert level.name == "Storage room"
    assert level.room_number == "376"


def test_parse_location_basement_room():
    level = parse_location_part("Storage room (U1)")
    assert level.room_number == "U1"


def test_parse_location_bare_number_and_room_prefix_converge():
    # "376", "Room 376" should normalise to the same canonical location.
    assert parse_location_part("376") == parse_location_part("Room 376")
    assert parse_location_part("376").name == "Room 376"
    assert parse_location_part("376").room_number == "376"


def test_parse_location_path_skips_blanks():
    path = parse_location_path("Storage room (376)", "Fridge 2", "")
    assert [level.name for level in path] == ["Storage room", "Fridge 2"]


def test_parse_tags_full_soup():
    parsed = parse_tags("Achtung,H319,H315,H335,WGK 1,LK 6.1D,2022")
    assert parsed.signal_word == "warning"
    assert parsed.hazard_codes == ["H319", "H315", "H335"]
    assert parsed.wgk == "1"
    assert parsed.storage_class == "6.1D"
    assert parsed.tags == ["2022"]


def test_parse_tags_combination_codes():
    parsed = parse_tags("Gefahr,H315+H319,P305-P351-P338")
    assert parsed.signal_word == "danger"
    assert parsed.hazard_codes == ["H315", "H319", "P305", "P351", "P338"]


def test_parse_tags_no_hazard_phrases_ignored():
    parsed = parse_tags("No hazard statements,2022")
    assert parsed.hazard_codes == []
    assert parsed.tags == ["2022"]


def test_parse_tags_na_values_dropped():
    parsed = parse_tags("WGK n/a,LK n/a,Soaking")
    assert parsed.wgk == ""
    assert parsed.storage_class == ""
    assert parsed.tags == ["Soaking"]


def test_parse_tags_suffixed_codes():
    # Codes keep their canonical GHS casing (H350i, not H350I) so they map to the catalog.
    parsed = parse_tags("Gefahr,H360FD,H350i,EUH059")
    assert parsed.hazard_codes == ["H360FD", "H350i", "EUH059"]


def test_parse_amount_in_stock():
    assert parse_amount_in_stock("1").value == Decimal("1")
    assert parse_amount_in_stock("empty").value is None
    assert parse_amount_in_stock("0,5").value == Decimal("0.5")
    junk = parse_amount_in_stock("4 Kartons")
    assert junk.value == Decimal("4") and junk.warning
