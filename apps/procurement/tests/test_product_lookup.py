"""Product-URL lookup: vendor matching, page parsing, caching, and the JSON endpoint.

No network: the transport seams (``product_lookup._get_html`` / ``_post_json``) are
monkeypatched with canned pages and GraphQL replies mirroring the real vendor responses
(probed 2026-07); the endpoint tests stub ``lookup`` itself.
"""

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.procurement import product_lookup
from apps.procurement.product_lookup import (
    ProductSuggestion,
    lookup,
    parse_money,
    split_product_url,
    valid_cas,
    vendor_for,
)
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab

SIGMA_URL = "https://www.sigmaaldrich.com/DE/de/product/sigma/gago20"
ROTH_URL = "https://www.carlroth.com/de/de/a-bis-z/ethanol-99-vergaellt/p/k928.4"
FISHER_URL = "https://www.fishersci.de/shop/products/sodium-chloride-acs/10428420"

# Trimmed to the structures the parsers read, copied from the live pages.
ROTH_PAGE = """
<html><head>
<title>Ethanol, 5 l, Kunststoff, CAS Nr. 64-17-5 | Alkohole | Carl Roth</title>
</head><body>
<p class="price"><span id="currentShownPrice">67,90&nbsp;€</span>/VE&nbsp;</p>
<p class="info-text">zzgl. MwSt. | 5&nbsp;l&nbsp;pro VE</p>
<p><b class="sku">Art.-Nr.</b> <b class="code" id="pdp-product-code">K928.4</b></p>
</body></html>
"""

FISHER_PAGE = """
<html><head>
<META PROPERTY="og:image" CONTENT="https://assets.fishersci.com/chemical-structure-cas-7647-14-5.jpg">
</head><body>
<h1 id="qa_item_header_text" itemprop="name" class="product_title_sec">
    Natriumchlorid, zertifiziertes AR, Fisher Chemical
</h1>
<span itemprop="priceCurrency" content="EUR"></span>
<b itemprop="price" content="51.25">51.25&nbsp;&euro;</b>
</body></html>
"""

JSONLD_PAGE = """
<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "HisTrap HP 5 x 1 ml",
 "sku": "17524701", "offers": {"@type": "Offer", "price": "412.00", "priceCurrency": "EUR"}}
</script></head><body></body></html>
"""


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail closed: any test that forgets to stub a transport seam gets None, not I/O."""
    monkeypatch.setattr(product_lookup, "_get_html", lambda url: None)
    monkeypatch.setattr(product_lookup, "_post_json", lambda url, payload, headers: None)


def _serve(monkeypatch, page):
    calls = []

    def fake_get_html(url):
        calls.append(url)
        return page

    monkeypatch.setattr(product_lookup, "_get_html", fake_get_html)
    return calls


# --- URL handling and vendor matching ----------------------------------------------------


def test_split_rejects_non_http_urls():
    assert split_product_url("ftp://carlroth.com/x") is None
    assert split_product_url("javascript:alert(1)") is None
    assert split_product_url("not a url") is None
    assert split_product_url("https://www.carlroth.com/p/x") is not None


@pytest.mark.parametrize(
    ("url", "vendor_name"),
    [
        (SIGMA_URL, "Merck (Sigma-Aldrich)"),
        (ROTH_URL, "Carl Roth"),
        (FISHER_URL, "Fisher Scientific"),
        ("https://us.vwr.com/store/product/7437636/sodium-chloride", "VWR (Avantor)"),
        ("https://www.cytivalifesciences.com/en/us/shop/histrap-hp-p-05656", "Cytiva"),
        ("https://www.amazon.de/dp/B0BSHF7WHW", "Amazon"),
        ("https://www.amazon.co.uk/gp/product/B0BSHF7WHW", "Amazon"),
    ],
)
def test_known_vendor_urls_match(url, vendor_name):
    parser = vendor_for(split_product_url(url))
    assert parser is not None and parser.vendor_name == vendor_name


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/product/123",
        # Lookalike hosts must not match (the allowlist is the SSRF guard).
        "https://sigmaaldrich.com.evil.example/product/sigma/g3660",
        "https://notcarlroth.com/p/k928.4",
        "https://internal.local/admin",
    ],
)
def test_unknown_and_lookalike_hosts_do_not_match(url):
    assert vendor_for(split_product_url(url)) is None


def test_client_vendor_spec_matches_what_the_server_accepts():
    """The form's button enables on exactly the URLs the lookup would accept."""
    spec = product_lookup.client_vendor_spec()
    assert {entry["name"] for entry in spec} == set(product_lookup.supported_vendor_names())
    for entry in spec:
        assert entry["hosts"], entry["name"]
        for host in entry["hosts"]:
            for candidate in (host, f"www.{host}", f"shop.eu.{host}"):
                parser = vendor_for(split_product_url(f"https://{candidate}/product/x"))
                assert parser is not None and parser.vendor_name == entry["name"], candidate
            # A lookalike that merely *contains* the host must not match it.
            assert vendor_for(split_product_url(f"https://{host}.evil.example/p/x")) is None


def test_unsupported_url_is_never_fetched(monkeypatch):
    calls = _serve(monkeypatch, "<html></html>")
    assert lookup("https://sigmaaldrich.com.evil.example/product/sigma/g3660") is None
    assert calls == []


# --- Helpers -----------------------------------------------------------------------------


def test_valid_cas_checksum():
    assert valid_cas("64-17-5")  # ethanol
    assert valid_cas("7647-14-5")  # sodium chloride
    assert not valid_cas("64-17-4")  # wrong check digit
    assert not valid_cas("12-34-5")
    assert not valid_cas("not-a-cas")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("67,90 €", ("67.90", "EUR")),
        ("$1,234.56", ("1234.56", "USD")),
        ("1.234,56 EUR", ("1234.56", "EUR")),
        ("51.25", ("51.25", "")),
        ("1.234", ("1234", "")),
        ("Preis auf Anfrage", ("", "")),
    ],
)
def test_parse_money(text, expected):
    assert parse_money(text) == expected


# --- Vendor page parsing (fixtures mirror the live markup) -------------------------------


def test_roth_page_yields_full_suggestion(monkeypatch):
    _serve(monkeypatch, ROTH_PAGE)
    assert lookup(ROTH_URL) == ProductSuggestion(
        vendor_name="Carl Roth",
        item_name="Ethanol, 5 l, Kunststoff",
        catalog_number="K928.4",
        cas_number="64-17-5",
        unit_price="67.90",
        currency="EUR",
        pack_size="5 l",
        live=True,
    )


def test_fisher_page_merges_microdata_and_url_catalog(monkeypatch):
    _serve(monkeypatch, FISHER_PAGE)
    suggestion = lookup(FISHER_URL)
    assert suggestion.item_name == "Natriumchlorid, zertifiziertes AR, Fisher Chemical"
    assert suggestion.catalog_number == "10428420"  # from the URL — not on the page
    assert suggestion.cas_number == "7647-14-5"  # from the structure-image URL
    assert suggestion.unit_price == "51.25"
    assert suggestion.currency == "EUR"
    assert suggestion.live is True


def test_jsonld_product_is_extracted_generically(monkeypatch):
    _serve(monkeypatch, JSONLD_PAGE)
    # A Cytiva URL without a -p-<id> suffix skips the API and falls through to the page.
    suggestion = lookup("https://www.cytivalifesciences.com/en/us/shop/histrap-hp")
    assert suggestion.item_name == "HisTrap HP 5 x 1 ml"
    assert suggestion.catalog_number == "17524701"
    assert suggestion.unit_price == "412.00"
    assert suggestion.currency == "EUR"


CYTIVA_URL = (
    "https://www.cytivalifesciences.com/en/us/shop/chromatography/"
    "prepacked-columns/predictor-mabselect-xtra-p-05656"
)

# Canned Cytiva product-details replies, trimmed from live responses (probed 2026-07).
CYTIVA_MULTI_VARIANT = {
    "name": "PreDictor™ MabSelect Xtra prepacked 96-well plates",
    "productCode": "P-05656",
    "variants": [
        {"productCode": "28943275", "name": "…6 µL per well", "packSize": "4 x 96-well plates"},
        {"productCode": "28943276", "name": "…20 µL per well", "packSize": "4 x 96-well plates"},
    ],
}
CYTIVA_SINGLE_VARIANT = {
    "name": "HiTrap™ Protein A HP",
    "productCode": "P-00123",
    "variants": [
        {
            "productCode": "17040201",
            "name": "HiTrap™ Protein A HP, 5 × 1 ml",
            "packSize": "5 x 1 ml",
        }
    ],
}


def _serve_cytiva_api(monkeypatch, reply):
    calls = []

    def fake_post_json(url, payload, headers):
        calls.append((url, payload, headers))
        return reply

    monkeypatch.setattr(product_lookup, "_post_json", fake_post_json)
    return calls


def test_cytiva_api_single_variant_gives_catalog_number(monkeypatch):
    _serve_cytiva_api(monkeypatch, CYTIVA_SINGLE_VARIANT)
    suggestion = lookup(CYTIVA_URL)
    assert suggestion.item_name == "HiTrap™ Protein A HP, 5 × 1 ml"
    assert suggestion.catalog_number == "17040201"
    assert suggestion.pack_size == "5 x 1 ml"
    assert suggestion.note == ""
    assert suggestion.live is True


def test_cytiva_api_multiple_variants_fills_name_and_notes(monkeypatch):
    calls = _serve_cytiva_api(monkeypatch, CYTIVA_MULTI_VARIANT)
    suggestion = lookup(CYTIVA_URL)
    assert suggestion.item_name == "PreDictor™ MabSelect Xtra prepacked 96-well plates"
    # The family id is not orderable, so no catalog number is guessed.
    assert suggestion.catalog_number == ""
    assert "2 order variants" in suggestion.note
    # Product id and locale come from the URL (language first, then country).
    assert calls[0][1] == {"productId": "p-05656", "language": "en", "country": "US"}


def test_cytiva_api_failure_falls_back_to_slug():
    # _no_network: the API and the page both yield nothing.
    suggestion = lookup(CYTIVA_URL)
    assert suggestion.item_name == "Predictor mabselect xtra"
    assert suggestion.live is False


def test_vwr_has_no_api_and_falls_back_to_slug(monkeypatch):
    # Avantor's OCC API is Cloudflare-gated; the parser must not attempt it.
    posts = []
    monkeypatch.setattr(
        product_lookup, "_post_json", lambda url, payload, headers: posts.append(url)
    )
    suggestion = lookup("https://us.vwr.com/store/product/7437636/sodium-chloride-acs")
    assert suggestion.item_name == "Sodium chloride acs"
    assert posts == []


def test_blocked_fetch_falls_back_to_url_data():
    # _no_network: both the GraphQL API and the page fetch yield nothing.
    assert lookup(SIGMA_URL) == ProductSuggestion(
        vendor_name="Merck (Sigma-Aldrich)",
        catalog_number="GAGO20",
        live=False,
    )


# Canned Sigma GraphQL replies, copied from live responses (probed 2026-07).
SIGMA_DETAIL_REPLY = {
    "data": {
        "getProductDetail": {
            "productNumber": "GAGO20",
            "name": "Glukose(GO)-Testkit",
            "casNumber": None,
        }
    }
}
SIGMA_PRICING_REPLY = {
    "data": {
        "getPricingForProduct": {
            "materialPricing": [{"listPrice": 145, "currency": "EUR", "packageSize": "1 kit"}]
        }
    }
}


def _serve_sigma_api(monkeypatch, detail, pricing):
    calls = []

    def fake_post_json(url, payload, headers):
        calls.append((url, payload, headers))
        return detail if "getProductDetail" in payload["query"] else pricing

    monkeypatch.setattr(product_lookup, "_post_json", fake_post_json)
    return calls


def test_sigma_api_yields_name_and_pricing(monkeypatch):
    calls = _serve_sigma_api(monkeypatch, SIGMA_DETAIL_REPLY, SIGMA_PRICING_REPLY)
    assert lookup(SIGMA_URL) == ProductSuggestion(
        vendor_name="Merck (Sigma-Aldrich)",
        item_name="Glukose(GO)-Testkit",
        catalog_number="GAGO20",
        unit_price="145",
        currency="EUR",
        pack_size="1 kit",
        live=True,
    )
    # Locale headers derive from the /DE/de/ URL path.
    assert all(call[2] == {"x-gql-country": "DE", "x-gql-language": "de"} for call in calls)


def test_sigma_api_reports_valid_cas(monkeypatch):
    detail = {
        "data": {
            "getProductDetail": {
                "productNumber": "E7023",
                "name": "Ethyl alcohol, Pure 200 proof",
                "casNumber": "64-17-5",
            }
        }
    }
    _serve_sigma_api(monkeypatch, detail, {"errors": [{"message": "boom"}], "data": None})
    suggestion = lookup("https://www.sigmaaldrich.com/US/en/product/sigald/e7023")
    assert suggestion.cas_number == "64-17-5"
    assert suggestion.unit_price == ""  # pricing errored, everything else survives


def test_sigma_api_error_falls_back_to_url(monkeypatch):
    _serve_sigma_api(monkeypatch, {"errors": [{"message": "No product found"}]}, None)
    assert lookup(SIGMA_URL) == ProductSuggestion(
        vendor_name="Merck (Sigma-Aldrich)",
        catalog_number="GAGO20",
        live=False,
    )


def test_spa_shell_falls_back_to_slug_name(monkeypatch):
    _serve(monkeypatch, "<html><body><div id='app'></div></body></html>")
    suggestion = lookup("https://us.vwr.com/store/product/7437636/sodium-chloride-acs")
    assert suggestion.item_name == "Sodium chloride acs"
    assert suggestion.live is False


def test_amazon_url_yields_asin_without_page(monkeypatch):
    monkeypatch.setattr(product_lookup, "_get_html", lambda url: None)
    suggestion = lookup("https://www.amazon.de/dp/B0BSHF7WHW?ref=something")
    assert suggestion.catalog_number == "B0BSHF7WHW"


AMAZON_PAGE = """
<html><head><title>Eppendorf Tubes : Amazon.de: Gewerbe</title></head><body>
<span id="productTitle" class="a-size-large product-title-word-break">
    Eppendorf 0030125150 Safe-Lock Tubes, 1,5 ml
</span>
<span itemprop="price" content="24.99"></span>
<span itemprop="priceCurrency" content="EUR"></span>
</body></html>
"""


def test_amazon_page_yields_title_but_never_a_price(monkeypatch):
    # Consumer prices differ from Amazon Business pricing — they must not prefill,
    # even when the page exposes them in machine-readable form.
    _serve(monkeypatch, AMAZON_PAGE)
    suggestion = lookup("https://www.amazon.de/dp/B0BSHF7WHW")
    assert suggestion.item_name == "Eppendorf 0030125150 Safe-Lock Tubes, 1,5 ml"
    assert suggestion.catalog_number == "B0BSHF7WHW"
    assert suggestion.unit_price == ""
    assert suggestion.currency == ""
    assert suggestion.live is True


def test_result_is_cached(monkeypatch):
    calls = _serve(monkeypatch, ROTH_PAGE)
    first = lookup(ROTH_URL)
    second = lookup(ROTH_URL)
    assert first == second
    assert len(calls) == 1


def test_empty_result_returns_none_and_is_cached(monkeypatch):
    calls = []

    def fake_get_html(url):
        calls.append(url)
        return None

    monkeypatch.setattr(product_lookup, "_get_html", fake_get_html)
    # A Cytiva URL with no usable slug yields nothing at all.
    url = "https://www.cytivalifesciences.com/"
    assert lookup(url) is None
    assert lookup(url) is None
    assert len(calls) == 1


# --- The JSON endpoint -------------------------------------------------------------------


@pytest.fixture
def lab(db):
    return create_lab(name="AG Lookup", item_id_prefix="AGL")


@pytest.fixture
def member(lab):
    user = User.objects.create_user(username="", email="member@x.de", password="pw")
    add_member(user=user, lab=lab, role_names=["Member"])
    return user


@pytest.mark.django_db
def test_endpoint_requires_login(client):
    resp = client.get(reverse("procurement:product_lookup"), {"url": ROTH_URL})
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_endpoint_rejects_malformed_url(client, member):
    client.force_login(member)
    resp = client.get(reverse("procurement:product_lookup"), {"url": "not a url"})
    assert resp.status_code == 400
    assert resp.json() == {"error": "invalid_url"}


@pytest.mark.django_db
def test_endpoint_reports_unsupported_vendor(client, member):
    client.force_login(member)
    resp = client.get(
        reverse("procurement:product_lookup"), {"url": "https://example.com/product/1"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is False
    assert data["reason"] == "unsupported"
    assert "Carl Roth" in data["supported"]


@pytest.mark.django_db
def test_endpoint_reports_nothing_found(client, member, monkeypatch):
    monkeypatch.setattr("apps.procurement.views.product_lookup_client.lookup", lambda url: None)
    client.force_login(member)
    resp = client.get(reverse("procurement:product_lookup"), {"url": ROTH_URL})
    assert resp.json() == {"found": False, "reason": "nothing"}


@pytest.mark.django_db
def test_endpoint_returns_fields_and_vendor_aliases(client, member, monkeypatch):
    monkeypatch.setattr(
        "apps.procurement.views.product_lookup_client.lookup",
        lambda url: ProductSuggestion(
            vendor_name="Carl Roth",
            item_name="Ethanol, 5 l, Kunststoff",
            catalog_number="K928.4",
            cas_number="64-17-5",
            unit_price="67.90",
            currency="EUR",
            pack_size="5 l",
            live=True,
        ),
    )
    client.force_login(member)
    data = client.get(reverse("procurement:product_lookup"), {"url": ROTH_URL}).json()
    assert data["found"] is True
    assert data["vendor"]["name"] == "Carl Roth"
    assert "Roth" in data["vendor"]["aliases"]
    assert data["fields"] == {
        "item_name": "Ethanol, 5 l, Kunststoff",
        "catalog_number": "K928.4",
        "cas_number": "64-17-5",
        "unit_price": "67.90",
        "currency": "EUR",
    }
    assert data["pack_size"] == "5 l"
    assert data["live"] is True


@pytest.mark.django_db
def test_request_form_ships_the_vendor_spec(client, member):
    """Without it the "Fetch details" button could never enable itself."""
    client.force_login(member)
    body = client.get(reverse("procurement:request_create")).content.decode()
    assert 'id="product-lookup-vendors"' in body
    assert "sigmaaldrich.com" in body
    assert "data-product-lookup-undo" in body


@pytest.mark.django_db
def test_endpoint_omits_empty_fields(client, member, monkeypatch):
    monkeypatch.setattr(
        "apps.procurement.views.product_lookup_client.lookup",
        lambda url: ProductSuggestion(vendor_name="Merck (Sigma-Aldrich)", catalog_number="GAGO20"),
    )
    client.force_login(member)
    data = client.get(reverse("procurement:product_lookup"), {"url": SIGMA_URL}).json()
    assert data["fields"] == {"catalog_number": "GAGO20"}
    assert data["live"] is False
