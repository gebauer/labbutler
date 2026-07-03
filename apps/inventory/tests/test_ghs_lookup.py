"""CAS → GHS lookup: PubChem response parsing, caching, and the JSON endpoint.

No network: the transport seam (``ghs_lookup._get_json``) is monkeypatched with canned
PUG/PUG-View payloads; the endpoint tests stub ``lookup_cas`` itself.
"""

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.inventory import ghs_lookup
from apps.inventory.ghs_lookup import CAS_RE, GhsSuggestion, lookup_cas
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab

ETHANOL_CAS = "64-17-5"

_CID_PAYLOAD = {"IdentifierList": {"CID": [702]}}

_GHS_PAYLOAD = {
    "Record": {
        "RecordType": "CID",
        "Section": [
            {
                "TOCHeading": "Safety and Hazards",
                "Section": [
                    {
                        "TOCHeading": "GHS Classification",
                        "Information": [
                            {
                                "Name": "Pictogram(s)",
                                "Value": {
                                    "StringWithMarkup": [
                                        {
                                            "String": "",
                                            "Markup": [
                                                {"Type": "Icon", "Extra": "Flammable"},
                                                {"Type": "Icon", "Extra": "Irritant"},
                                                {"Type": "Icon", "Extra": "Flammable"},
                                            ],
                                        }
                                    ]
                                },
                            },
                            {
                                "Name": "Signal",
                                "Value": {"StringWithMarkup": [{"String": "Danger"}]},
                            },
                            {
                                "Name": "Signal",
                                "Value": {"StringWithMarkup": [{"String": "Warning"}]},
                            },
                            {
                                "Name": "GHS Hazard Statements",
                                "Value": {
                                    "StringWithMarkup": [
                                        {
                                            "String": "H225 (>99.9%): Highly Flammable liquid"
                                            " and vapor [Danger Flammable liquids]"
                                        },
                                        {
                                            "String": "H319 (~55%): Causes serious eye"
                                            " irritation [Warning]"
                                        },
                                        # A second SDS source repeating a code, and one
                                        # the catalog doesn't know.
                                        {"String": "H225: Highly flammable liquid and vapour"},
                                        {"String": "H999: Not a real statement"},
                                        {"String": "Not classified"},
                                    ]
                                },
                            },
                            {
                                "Name": "Precautionary Statement Codes",
                                "Value": {
                                    "StringWithMarkup": [{"String": "P210, P233, P305+P351+P338"}]
                                },
                            },
                        ],
                    }
                ],
            }
        ],
    }
}


# A record carrying the EU harmonised classification (CLP Annex VI) next to ECHA
# notifier statistics — the harmonised codes must be picked out by source.
_HARMONIZED_PAYLOAD = {
    "Record": {
        "Reference": [
            {
                "ReferenceNumber": 1,
                "SourceName": "Regulation (EC) No 1272/2008 of the European Parliament"
                " and of the Council",
            },
            {"ReferenceNumber": 2, "SourceName": "European Chemicals Agency (ECHA)"},
        ],
        "Section": [
            {
                "TOCHeading": "GHS Classification",
                "Information": [
                    {
                        "Name": "GHS Hazard Statements",
                        "ReferenceNumber": 1,
                        "Value": {
                            "StringWithMarkup": [
                                {"String": "H314: Causes severe skin burns and eye damage"},
                                {"String": "H331: Toxic if inhaled"},
                            ]
                        },
                    },
                    {
                        "Name": "GHS Hazard Statements",
                        "ReferenceNumber": 2,
                        "Value": {
                            "StringWithMarkup": [
                                {"String": "H314 (99.9%): Causes severe skin burns"},
                                {"String": "H335 (59%): May cause respiratory irritation"},
                                {"String": "H290 (22.8%): May be corrosive to metals"},
                            ]
                        },
                    },
                ],
            }
        ],
    }
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def pubchem(monkeypatch):
    """Serve canned PubChem payloads and count upstream calls."""
    calls = []

    def fake_get_json(url):
        calls.append(url)
        if "/cids/JSON" in url:
            return _CID_PAYLOAD
        return _GHS_PAYLOAD

    monkeypatch.setattr(ghs_lookup, "_get_json", fake_get_json)
    return calls


def test_cas_regex():
    assert CAS_RE.match("64-17-5")
    assert CAS_RE.match("7732-18-5")
    assert not CAS_RE.match("64-17-55")
    assert not CAS_RE.match("ethanol")
    assert not CAS_RE.match("64175")


def test_lookup_parses_signal_hazards_and_pictograms(pubchem):
    suggestion = lookup_cas(ETHANOL_CAS)
    assert suggestion == GhsSuggestion(
        signal_word="danger",  # the more severe of the two source records wins
        hazard_codes=["H225", "H319", "P210", "P233", "P305+P351+P338"],
        pictograms=["Flammable", "Irritant"],  # deduped, order kept
        percentages={"H225": 99.9, "H319": 55.0},  # "(>99.9%)" / "(~55%)" annotations
    )


def test_unknown_and_duplicate_codes_are_dropped(pubchem):
    codes = lookup_cas(ETHANOL_CAS).hazard_codes
    assert "H999" not in codes  # not in the seeded catalog
    assert codes.count("H225") == 1


def test_invalid_cas_never_hits_the_network(pubchem):
    assert lookup_cas("not-a-cas") is None
    assert pubchem == []


def test_found_result_is_cached(pubchem):
    first = lookup_cas(ETHANOL_CAS)
    second = lookup_cas(ETHANOL_CAS)
    assert first == second
    assert len(pubchem) == 2  # one CID + one GHS call, no repeat for the second lookup


def test_unresolvable_cas_returns_none_and_is_cached(monkeypatch):
    calls = []

    def fake_get_json(url):
        calls.append(url)
        return None

    monkeypatch.setattr(ghs_lookup, "_get_json", fake_get_json)
    assert lookup_cas(ETHANOL_CAS) is None
    assert lookup_cas(ETHANOL_CAS) is None
    assert len(calls) == 1  # the negative result is cached too


def test_harmonized_clp_codes_are_extracted_by_source(monkeypatch):
    monkeypatch.setattr(
        ghs_lookup,
        "_get_json",
        lambda url: _CID_PAYLOAD if "/cids/JSON" in url else _HARMONIZED_PAYLOAD,
    )
    suggestion = lookup_cas(ETHANOL_CAS)
    assert suggestion.harmonized_codes == ["H314", "H331"]
    assert suggestion.hazard_codes == ["H314", "H331", "H335", "H290"]
    assert suggestion.percentages == {"H314": 99.9, "H335": 59.0, "H290": 22.8}


def test_compound_without_ghs_section_returns_none(monkeypatch):
    payloads = {"cids": _CID_PAYLOAD, "view": {"Record": {"Section": []}}}
    monkeypatch.setattr(
        ghs_lookup,
        "_get_json",
        lambda url: payloads["cids"] if "/cids/JSON" in url else payloads["view"],
    )
    assert lookup_cas(ETHANOL_CAS) is None


# --- The JSON endpoint -------------------------------------------------------------------


@pytest.fixture
def lab(db):
    return create_lab(name="AG Lookup", item_id_prefix="AGL")


@pytest.fixture
def viewer(lab):
    user = User.objects.create_user(username="", email="view@x.de", password="pw")
    add_member(user=user, lab=lab, role_names=["Viewer"])
    return user


@pytest.mark.django_db
def test_endpoint_requires_login(client):
    resp = client.get(reverse("inventory:ghs_lookup"), {"cas": ETHANOL_CAS})
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_endpoint_rejects_malformed_cas(client, viewer):
    client.force_login(viewer)
    resp = client.get(reverse("inventory:ghs_lookup"), {"cas": "ethanol"})
    assert resp.status_code == 400
    assert resp.json() == {"error": "invalid_cas"}


@pytest.mark.django_db
def test_endpoint_reports_not_found(client, viewer, monkeypatch):
    monkeypatch.setattr("apps.inventory.views.ghs_lookup_client.lookup_cas", lambda cas: None)
    client.force_login(viewer)
    resp = client.get(reverse("inventory:ghs_lookup"), {"cas": ETHANOL_CAS})
    assert resp.status_code == 200
    assert resp.json() == {"found": False}


@pytest.mark.django_db
def test_endpoint_returns_codes_with_catalog_text(client, viewer, monkeypatch):
    monkeypatch.setattr(
        "apps.inventory.views.ghs_lookup_client.lookup_cas",
        lambda cas: GhsSuggestion(
            signal_word="danger",
            hazard_codes=["P210", "P405", "H319", "H225", "H336"],
            pictograms=["Flammable", "Corrosion proposal"],
            percentages={"H225": 95.0, "H319": 12.5},
        ),
    )
    client.force_login(viewer)
    resp = client.get(reverse("inventory:ghs_lookup"), {"cas": ETHANOL_CAS})
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert data["signal_word"] == "danger"
    # H before P, alphabetical within; texts from the seeded catalog rows.
    assert [h["code"] for h in data["hazards"]] == ["H225", "H319", "H336", "P210", "P405"]
    assert data["hazards"][0]["text"] == "Highly flammable liquid and vapour"
    assert data["hazards"][0]["kind"] == "H"
    by_code = {h["code"]: h for h in data["hazards"]}
    # Majority-reported codes are suggested; minority ones are not.
    assert by_code["H225"] == {**by_code["H225"], "percent": 95.0, "suggested": True}
    assert by_code["H319"] == {**by_code["H319"], "percent": 12.5, "suggested": False}
    # An H-code without a share next to annotated ones is a side-source: rare.
    assert by_code["H336"] == {**by_code["H336"], "percent": None, "suggested": False}
    # P-statements carry no notifier shares; they are suggested iff the GHS recommends
    # them for an accepted H-code (P210 is listed for H225, storage code P405 is not).
    assert by_code["P210"] == {**by_code["P210"], "percent": None, "suggested": True}
    assert by_code["P405"] == {**by_code["P405"], "percent": None, "suggested": False}
    # Known pictogram names map to GHS codes + static icons; unknown ones degrade.
    assert data["pictograms"][0] == {
        "name": "Flammable",
        "code": "GHS02",
        "icon": "/static/img/ghs/GHS02.svg",
    }
    assert data["pictograms"][1] == {"name": "Corrosion proposal", "code": None, "icon": None}


@pytest.mark.django_db
def test_endpoint_prefers_harmonized_classification(client, viewer, monkeypatch):
    monkeypatch.setattr(
        "apps.inventory.views.ghs_lookup_client.lookup_cas",
        lambda cas: GhsSuggestion(
            signal_word="danger",
            hazard_codes=["H314", "H331", "H335", "H290", "P280", "P210"],
            pictograms=[],
            percentages={"H314": 99.9, "H331": 49.4, "H335": 59.0, "H290": 22.8},
            harmonized_codes=["H314", "H331"],
        ),
    )
    client.force_login(viewer)
    data = client.get(reverse("inventory:ghs_lookup"), {"cas": ETHANOL_CAS}).json()
    by_code = {h["code"]: h for h in data["hazards"]}
    # The legally binding set wins: H331 in despite 49.4%, H335 out despite 59%.
    assert by_code["H314"]["suggested"] is True
    assert by_code["H331"]["suggested"] is True
    assert by_code["H335"]["suggested"] is False
    assert by_code["H290"]["suggested"] is False
    # P ranking follows the harmonised H-set (P280 fits H314; P210 is flammability-only).
    assert by_code["P280"]["suggested"] is True
    assert by_code["P210"]["suggested"] is False


@pytest.mark.django_db
def test_endpoint_suggests_all_h_codes_without_any_notifier_data(client, viewer, monkeypatch):
    monkeypatch.setattr(
        "apps.inventory.views.ghs_lookup_client.lookup_cas",
        lambda cas: GhsSuggestion(signal_word="", hazard_codes=["H225", "H336"], pictograms=[]),
    )
    client.force_login(viewer)
    resp = client.get(reverse("inventory:ghs_lookup"), {"cas": ETHANOL_CAS})
    assert all(h["suggested"] for h in resp.json()["hazards"])
