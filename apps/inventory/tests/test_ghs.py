"""GHS catalog tests: code canonicalisation, catalog content, and migration seeding."""

import pytest

from apps.inventory import ghs
from apps.inventory.models import HazardStatement


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("h319", "H319"),
        (" H319 ", "H319"),
        ("euh066", "EUH066"),
        ("p305", "P305"),
        ("H350i", "H350i"),
        ("H350I", "H350i"),  # blind upper-casing is corrected
        ("H360FD", "H360FD"),
        ("H360DF", "H360FD"),  # F ordered before D
        ("H360F", "H360F"),
        ("H360D", "H360D"),
        ("H361D", "H361d"),  # suspected -> lower-case suffix
        ("H361F", "H361f"),
        ("H360Fd", "H360Fd"),  # F presumed, d suspected
        ("H360fD", "H360Df"),  # order-free: f suspected + D presumed -> canonical H360Df
        ("H360Df", "H360Df"),
        ("euh201a", "EUH201A"),  # EUH suffix stays upper (snapped to catalog)
        ("EUH201A", "EUH201A"),
    ],
)
def test_canonical_code(raw, expected):
    assert ghs.canonical_code(raw) == expected


def test_kind_for():
    assert ghs.kind_for("H319") == "H"
    assert ghs.kind_for("EUH066") == "EUH"
    assert ghs.kind_for("P305") == "P"


def test_catalog_wording_is_correct():
    assert ghs.STATEMENTS_EN["H319"] == "Causes serious eye irritation"
    assert ghs.STATEMENTS_EN["H350i"] == "May cause cancer by inhalation"
    assert ghs.STATEMENTS_EN["H360D"] == "May damage the unborn child"
    assert ghs.STATEMENTS_EN["EUH066"] == "Repeated exposure may cause skin dryness or cracking"
    # Combined statements are catalogued too.
    assert "P305+P351+P338" in ghs.STATEMENTS_EN


@pytest.mark.django_db
def test_migration_seeded_the_catalog():
    hs = HazardStatement.objects.get(code="H319")
    assert hs.text_en == "Causes serious eye irritation"
    assert hs.kind == "H"
    # Canonical casing is what got seeded.
    assert HazardStatement.objects.filter(code="H350i").exists()
    # A precautionary statement is classified as P.
    assert HazardStatement.objects.get(code="P280").kind == "P"


def test_recommended_p_parts_for_corrosive():
    parts = ghs.recommended_p_parts(["H314"])
    # Old-revision CLP codes must match the newer-revision recommendation table.
    assert ghs.is_recommended_p("P305+P351+P338", parts)
    assert ghs.is_recommended_p("P303+P361+P353", parts)
    assert ghs.is_recommended_p("P310", parts)
    assert ghs.is_recommended_p("P280", parts)
    # Unrelated prevention/storage codes are not recommended for corrosion alone.
    assert not ghs.is_recommended_p("P210", parts)
    assert not ghs.is_recommended_p("P410+P412", parts)


def test_recommended_p_parts_unions_multiple_h_codes():
    parts = ghs.recommended_p_parts(["H225", "H319"])
    assert ghs.is_recommended_p("P210", parts)  # from flammability
    assert ghs.is_recommended_p("P305+P351+P338", parts)  # from eye irritation


def test_recommended_p_parts_fails_open_without_data():
    assert ghs.recommended_p_parts([]) is None
    assert ghs.recommended_p_parts(["EUH029"]) is None


def test_pictograms_for_hazard_codes():
    assert ghs.pictograms_for("H314") == ("GHS05",)
    assert ghs.pictograms_for("H300+H310") == ("GHS06",)
    # Aquatic Chronic 3 carries no pictogram; P/EUH statements never do.
    assert ghs.pictograms_for("H412") == ()
    assert ghs.pictograms_for("P210") == ()


@pytest.mark.django_db
def test_hazard_widget_tags_options_with_pictograms():
    from apps.inventory.forms import hazard_statement_field

    field = hazard_statement_field()
    html = field.widget.render("hazards", [])
    assert 'value="H314" data-pictograms="GHS05"' in html
    assert 'value="H412"' in html and 'value="H412" data-pictograms' not in html
