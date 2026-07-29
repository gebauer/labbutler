"""Product URL → request-form prefill for known lab vendors.

Best-effort *suggestions* for the request form: the pasted product URL is matched
against a registry of vendor parsers, the product page is fetched server-side, and
name / catalog number / CAS / price are extracted from whatever structure the shop
exposes (JSON-LD, microdata, OpenGraph, vendor-specific markup). Every failure mode —
network, bot walls, layout drift — degrades to whatever can be read from the URL path
alone (Sigma catalog numbers, Amazon ASINs, VWR/Cytiva slugs); nothing here may ever
block the form.

The vendor registry doubles as the SSRF guard: only http(s) URLs whose hostname matches
a registered vendor pattern are ever fetched, so the endpoint cannot be pointed at
internal services. Reality per vendor (probed 2026-07):

- Carl Roth and Fisher Scientific serve full server-rendered pages — rich data.
- Sigma-Aldrich (Merck) resets non-browser TLS connections on the HTML pages, but the
  site's own GraphQL API (www.sigmaaldrich.com/api, the one the Next.js frontend
  calls) answers plain POSTs — the parser queries it for name, CAS and list price.
  Unofficial, so schema drift degrades to the catalog number from the URL.
- Cytiva ships an empty SPA shell, but its product-details service
  (api.cytivalifesciences.com/oc-product-details/v1) answers plain POSTs — queried for
  the product name and, where unambiguous, the variant's catalog code and pack size.
  Its pricing service wants an undocumented payload and Cytiva prices are contract-
  based anyway, so no price is taken.
- VWR/Avantor is a dead end: the pages are SPA shells and their SAP Commerce API
  (occapi.avantorsciences.com) is behind a Cloudflare challenge. Only the URL slug is
  usable. Do not try to work around the challenge — if VWR data matters, ask Avantor
  for punchout/API access.
- Amazon serves full pages to plain clients; the parser reads only the title (plus the
  ASIN from the URL) — consumer prices are deliberately ignored, they differ from
  Amazon Business pricing. (No usable official API: PA-API is affiliate-gated and
  deprecated 2026; the Amazon Business Product Search API needs an OAuth app
  registered on the lab's AB account — worth revisiting only if scraping breaks.)

Results are cached via the default Django cache (per-process LocMemCache today — fine
for a courtesy cache behind a manual button press).
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

from django.core.cache import cache

_TIMEOUT_SECONDS = 8
_MAX_PAGE_BYTES = 5 * 1024 * 1024  # Amazon product pages run to several MB
_USER_AGENT = "LabButler/1.0 (+https://github.com/gebauer/labbutler)"

_POSITIVE_TTL = 24 * 3600  # prices drift — keep found data a day at most
_NEGATIVE_TTL = 3600  # bot walls and outages may be transient
_CACHE_MISS = {"found": False}


@dataclass(frozen=True)
class ProductSuggestion:
    """What a vendor page (or its URL) yields, reduced to the request-form fields."""

    vendor_name: str = ""
    item_name: str = ""
    catalog_number: str = ""
    cas_number: str = ""
    unit_price: str = ""  # decimal string, e.g. "67.90"
    currency: str = ""  # ISO code, e.g. "EUR"
    pack_size: str = ""  # informational only ("5 l"), shown next to the price fields
    note: str = ""  # vendor-specific hint for the user, e.g. "4 order variants exist"
    live: bool = False  # fetched from the shop (page or API), vs. URL-derived guesses only


@dataclass(frozen=True)
class VendorParser:
    """One shop the lookup understands.

    A URL belongs to this vendor when its hostname *is* one of ``hosts`` or is a
    subdomain of one — so ``www.sigmaaldrich.com`` matches while the lookalike
    ``sigmaaldrich.com.evil.example`` does not. The rule is deliberately simple enough
    for the form's JavaScript to mirror exactly (see :func:`client_vendor_spec`), so the
    "Fetch details" button enables on precisely the URLs the server would accept.

    ``aliases`` are alternative names the client uses to find the vendor in the lab's own
    vendor list. ``from_api`` (a vendor JSON API, tried before the HTML page) and
    ``from_page`` are both optional.
    """

    vendor_name: str
    domain: str  # registrable name without the TLD, e.g. "carlroth"
    tlds: tuple[str, ...]  # country shops the vendor runs, e.g. ("com", "de")
    from_url: Callable[[SplitResult], dict]
    from_api: Callable[[SplitResult], dict] | None = None
    from_page: Callable[[str], dict] | None = None
    aliases: tuple[str, ...] = ()
    # Suggestion fields never taken from this vendor, whichever extractor found them
    # (e.g. Amazon consumer prices, which differ from Amazon Business pricing).
    drop_fields: tuple[str, ...] = ()

    @property
    def hosts(self) -> list[str]:
        return [f"{self.domain}.{tld}" for tld in self.tlds]

    def matches(self, host: str) -> bool:
        host = (host or "").lower()
        return any(host == known or host.endswith(f".{known}") for known in self.hosts)


def split_product_url(raw_url: str) -> SplitResult | None:
    """Parse an http(s) product URL; ``None`` for anything else."""
    try:
        parts = urlsplit((raw_url or "").strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return parts


def vendor_for(parts: SplitResult) -> VendorParser | None:
    host = parts.hostname or ""
    for parser in PARSERS:
        if parser.matches(host):
            return parser
    return None


def supported_vendor_names() -> list[str]:
    return [parser.vendor_name for parser in PARSERS]


def client_vendor_spec() -> list[dict]:
    """The vendor list the request form's JS needs to mirror :meth:`VendorParser.matches`.

    Serialized into the page so the "Fetch details" button can enable itself on exactly
    the URLs this module would accept — without a round trip per keystroke.
    """
    return [{"name": parser.vendor_name, "hosts": parser.hosts} for parser in PARSERS]


def lookup(raw_url: str) -> ProductSuggestion | None:
    """Product data for a supported vendor URL, or ``None``. Cached per URL."""
    parts = split_product_url(raw_url)
    if parts is None:
        return None
    parser = vendor_for(parts)
    if parser is None:
        return None

    cache_key = "product-lookup:" + hashlib.sha256(parts.geturl().encode()).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        if not cached["found"]:
            return None
        return ProductSuggestion(**cached["data"])

    suggestion = _build_suggestion(parser, parts)
    if suggestion is None:
        cache.set(cache_key, _CACHE_MISS, _NEGATIVE_TTL)
        return None
    cache.set(cache_key, {"found": True, "data": suggestion.__dict__}, _POSITIVE_TTL)
    return suggestion


def _build_suggestion(parser: VendorParser, parts: SplitResult) -> ProductSuggestion | None:
    live_data: dict = {}
    if parser.from_api is not None:
        live_data = {k: v for k, v in parser.from_api(parts).items() if v}
    if not live_data:
        page = _get_html(parts.geturl())
        if page:
            live_data = _generic_from_page(page)
            if parser.from_page is not None:
                # Vendor-specific extraction beats the generic heuristics.
                live_data.update({k: v for k, v in parser.from_page(page).items() if v})
    data = dict(live_data)
    for name, value in parser.from_url(parts).items():
        data.setdefault(name, value)
    data = {name: value for name, value in data.items() if value and name not in parser.drop_fields}
    if not data:
        return None
    return ProductSuggestion(
        vendor_name=parser.vendor_name,
        live=any(live_data.values()),
        **data,
    )


def _get_html(url: str) -> str | None:
    """GET a page as text; ``None`` on any transport or HTTP problem.

    The single seam tests monkeypatch — everything above it is pure parsing.
    """
    request = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            raw = response.read(_MAX_PAGE_BYTES)
    except (OSError, ValueError):
        return None
    return raw.decode("utf-8", errors="replace")


def _post_json(url: str, payload: dict, headers: dict) -> dict | None:
    """POST JSON and decode the JSON reply; ``None`` on any transport or HTTP problem.

    The second transport seam tests monkeypatch (Sigma's GraphQL API).
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


# --- Generic page extraction --------------------------------------------------------------

_JSONLD_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_OG_TITLE_RE = re.compile(r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"', re.I)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_MICRO_PRICE_RE = re.compile(r'itemprop="price"[^>]*content="([^"]+)"', re.I)
_MICRO_CURRENCY_RE = re.compile(r'itemprop="priceCurrency"[^>]*content="([A-Za-z]{3})"', re.I)

# A CAS number only counts with "CAS" nearby (spec tables, titles) or in a
# chemical-structure image URL — bare \d+-\d\d-\d matches far too much.
_CAS_CONTEXT_RE = re.compile(r"CAS[^<>{}]{0,40}?(\d{2,7}-\d{2}-\d)")
_CAS_IMAGE_RE = re.compile(r"cas-(\d{2,7}-\d{2}-\d)")


def valid_cas(cas: str) -> bool:
    """CAS registry checksum: digits reversed, weighted 1..n, mod 10 = check digit."""
    if not re.fullmatch(r"\d{2,7}-\d{2}-\d", cas):
        return False
    digits = cas.replace("-", "")
    body, check = digits[:-1], int(digits[-1])
    return sum(int(d) * i for i, d in enumerate(reversed(body), start=1)) % 10 == check


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value).replace("\xa0", " ")).strip()


def parse_money(text: str) -> tuple[str, str]:
    """``("67.90", "EUR")`` from strings like ``67,90 €`` / ``$1,234.56``; empty on failure."""
    text = _clean_text(text)
    currency = ""
    for token, code in (("€", "EUR"), ("$", "USD"), ("£", "GBP"), ("CHF", "CHF")):
        if token in text:
            currency = code
            break
    else:
        iso = re.search(r"\b(EUR|USD|GBP|CHF)\b", text, re.I)
        if iso:
            currency = iso.group(1).upper()
    number = re.search(r"\d[\d.,]*", text)
    if not number:
        return "", ""
    amount = number.group(0)
    if "," in amount and "." in amount:
        decimal_sep = "," if amount.rindex(",") > amount.rindex(".") else "."
    elif "," in amount or "." in amount:
        sep = "," if "," in amount else "."
        # One separator: decimal point iff it looks like cents ("67,9", "51.25");
        # exactly three trailing digits is a thousands group ("1.234").
        decimal_sep = sep if len(amount) - amount.rindex(sep) - 1 in (1, 2) else ""
    else:
        decimal_sep = ""
    integer, fraction = amount, ""
    if decimal_sep:
        integer, fraction = amount.rsplit(decimal_sep, 1)
    integer = re.sub(r"[.,]", "", integer)
    value = integer + ("." + fraction if fraction else "")
    return value, currency


def _page_title(page: str) -> str:
    og = _OG_TITLE_RE.search(page)
    if og and _clean_text(og.group(1)):
        return _clean_text(og.group(1))
    title = _TITLE_RE.search(page)
    return _clean_text(title.group(1)) if title else ""


def _find_cas(page: str) -> str:
    for pattern in (_CAS_CONTEXT_RE, _CAS_IMAGE_RE):
        for match in pattern.finditer(page):
            if valid_cas(match.group(1)):
                return match.group(1)
    return ""


def _jsonld_products(page: str):
    """All ``@type: Product`` objects in the page's JSON-LD blocks, however nested."""

    def walk(node):
        if isinstance(node, dict):
            if node.get("@type") == "Product":
                yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for entry in node:
                yield from walk(entry)

    for block in _JSONLD_RE.finditer(page):
        try:
            payload = json.loads(block.group(1))
        except ValueError:
            continue
        yield from walk(payload)


def _generic_from_page(page: str) -> dict:
    data: dict = {}
    for product in _jsonld_products(page):
        if product.get("name"):
            data.setdefault("item_name", _clean_text(str(product["name"])))
        sku = product.get("sku") or product.get("mpn")
        if sku:
            data.setdefault("catalog_number", _clean_text(str(sku)))
        offers = product.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = offers.get("price") or offers.get("lowPrice")
        if price:
            amount, currency = parse_money(str(price))
            if amount:
                data.setdefault("unit_price", amount)
        if offers.get("priceCurrency"):
            data.setdefault("currency", str(offers["priceCurrency"]).upper())

    price_match = _MICRO_PRICE_RE.search(page)
    if price_match:
        amount, _ = parse_money(price_match.group(1))
        if amount:
            data.setdefault("unit_price", amount)
    currency_match = _MICRO_CURRENCY_RE.search(page)
    if currency_match:
        data.setdefault("currency", currency_match.group(1).upper())

    title = _page_title(page)
    if title:
        data.setdefault("item_name", title)
    cas = _find_cas(page)
    if cas:
        data.setdefault("cas_number", cas)
    return {name: value for name, value in data.items() if value}


def _name_from_slug(slug: str) -> str:
    words = _clean_text(slug.replace("-", " ").replace("_", " "))
    return words[:1].upper() + words[1:] if words else ""


# --- Vendor parsers -----------------------------------------------------------------------


def _sigma_from_url(parts: SplitResult) -> dict:
    # /DE/de/product/<brand>/<code> — the code is the orderable product number.
    match = re.search(r"/product/[^/]+/([^/?#]+)", parts.path)
    return {"catalog_number": match.group(1).upper()} if match else {}


_SIGMA_API = "https://www.sigmaaldrich.com/api"

_SIGMA_DETAIL_QUERY = """query ($brand: String!, $productKey: String!) {
  getProductDetail(input: {brandKey: $brand, productKey: $productKey}) {
    productNumber name casNumber
  }
}"""

_SIGMA_PRICING_QUERY = """query ($brand: String!, $productNumber: String!) {
  getPricingForProduct(input: {brand: $brand, productNumber: $productNumber, quantity: 1}) {
    materialPricing { listPrice currency packageSize }
  }
}"""


def _sigma_locale(parts: SplitResult) -> tuple[str, str]:
    """Country/language from the URL path (``/DE/de/…``); Germany when absent."""
    match = re.match(r"/([A-Za-z]{2})/([A-Za-z]{2})/", parts.path)
    return (match.group(1).upper(), match.group(2).lower()) if match else ("DE", "de")


def _sigma_from_api(parts: SplitResult) -> dict:
    """Query Sigma's frontend GraphQL API — the HTML pages block non-browser clients.

    Two POSTs like the shop itself makes: product detail (name, CAS), then list
    pricing for the first (usually smallest) package. Each degrades independently.
    """
    match = re.search(r"/product/([^/]+)/([^/?#]+)", parts.path)
    if not match:
        return {}
    brand, product_key = match.group(1).lower(), match.group(2).lower()
    country, language = _sigma_locale(parts)
    headers = {"x-gql-country": country, "x-gql-language": language}

    data: dict = {}
    detail = _post_json(
        _SIGMA_API,
        {"query": _SIGMA_DETAIL_QUERY, "variables": {"brand": brand, "productKey": product_key}},
        headers,
    )
    product = ((detail or {}).get("data") or {}).get("getProductDetail") or {}
    if product.get("name"):
        # Names may carry markup like "…<SUB>2</SUB>…" — keep the text only.
        data["item_name"] = _clean_text(re.sub(r"<[^>]+>", "", str(product["name"])))
    if product.get("productNumber"):
        data["catalog_number"] = _clean_text(str(product["productNumber"]))
    if valid_cas(str(product.get("casNumber") or "")):
        data["cas_number"] = str(product["casNumber"])

    pricing = _post_json(
        _SIGMA_API,
        {
            "query": _SIGMA_PRICING_QUERY,
            "variables": {
                "brand": brand,
                "productNumber": data.get("catalog_number") or product_key.upper(),
            },
        },
        headers,
    )
    materials = (((pricing or {}).get("data") or {}).get("getPricingForProduct") or {}).get(
        "materialPricing"
    ) or []
    if materials:
        cheapest = materials[0]
        if cheapest.get("listPrice"):
            amount, _ = parse_money(str(cheapest["listPrice"]))
            data["unit_price"] = amount
        if cheapest.get("currency"):
            data["currency"] = str(cheapest["currency"]).upper()
        if cheapest.get("packageSize"):
            data["pack_size"] = _clean_text(str(cheapest["packageSize"]))
    return data


def _sigma_from_page(page: str) -> dict:
    # The page is Next.js; when a fetch does get through, the embedded JSON state
    # carries the product record. Keys observed in sigmaaldrich.com's data blobs.
    data = {}
    for key, target in (("productNumber", "catalog_number"), ("casNumber", "cas_number")):
        match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', page)
        if match:
            data[target] = _clean_text(match.group(1))
    if data.get("cas_number") and not valid_cas(data["cas_number"]):
        del data["cas_number"]
    return data


def _roth_from_url(parts: SplitResult) -> dict:
    match = re.search(r"/p/([^/?#]+)", parts.path)
    return {"catalog_number": match.group(1).upper()} if match else {}


def _roth_from_page(page: str) -> dict:
    data = {}
    code = re.search(r'id="pdp-product-code"[^>]*>([^<]+)<', page)
    if code:
        data["catalog_number"] = _clean_text(code.group(1))
    price = re.search(r'id="currentShownPrice"[^>]*>([^<]+)<', page)
    if price:
        amount, currency = parse_money(price.group(1))
        data["unit_price"], data["currency"] = amount, currency
    # The <title> is "«name», CAS Nr. «cas» | «category» | …" — the first segment
    # minus the CAS suffix is the product name (incl. pack size, which is useful).
    title = _page_title(page)
    if title:
        name = title.split(" | ")[0]
        name = re.sub(r",?\s*CAS\s*Nr\.\s*[\d-]+\s*$", "", name).strip(" ,")
        if name:
            data["item_name"] = name
    pack = re.search(r"\|\s*([^<>|]{1,40}?)\s*pro\s*VE", _clean_text(page))
    if pack:
        data["pack_size"] = pack.group(1).strip()
    return data


def _fisher_from_url(parts: SplitResult) -> dict:
    match = re.search(r"/products/[^/]+/([^/?#]+)/?$", parts.path)
    return {"catalog_number": match.group(1)} if match else {}


def _fisher_from_page(page: str) -> dict:
    data = {}
    # Breadcrumbs also carry itemprop="name"; the product name is the <h1>.
    name = re.search(r'<h1[^>]*itemprop="name"[^>]*>\s*([^<]+)', page)
    if name:
        data["item_name"] = _clean_text(name.group(1))
    return data


def _vwr_from_url(parts: SplitResult) -> dict:
    # /store/product/<internal-id>/<slug> — the id is not the catalog number, so the
    # slug-derived name is all the URL offers.
    match = re.search(r"/store/product/\d+/([^/?#]+)", parts.path)
    return {"item_name": _name_from_slug(match.group(1))} if match else {}


def _cytiva_from_url(parts: SplitResult) -> dict:
    slug = parts.path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"-p-\d+$", "", slug)  # trailing internal page id
    return {"item_name": _name_from_slug(slug)} if slug else {}


_CYTIVA_API = "https://api.cytivalifesciences.com/oc-product-details/v1/details"


def _cytiva_from_api(parts: SplitResult) -> dict:
    """Query Cytiva's product-details service — the shop itself is an empty SPA shell.

    A Cytiva URL addresses a product *family* (``…-p-05656``), which may hold several
    orderable variants. With exactly one variant its catalog code is unambiguous; with
    several, only the family name is filled and the user picks the size themselves.
    """
    product_id = re.search(r"-(p-\d+)(?:[/?#]|$)", parts.path, re.I)
    if not product_id:
        return {}
    # Path locale is /<language>/<country>/ — the reverse of Sigma's order.
    locale = re.match(r"/([A-Za-z]{2})/([A-Za-z]{2})/", parts.path)
    language, country = (
        (locale.group(1).lower(), locale.group(2).upper()) if locale else ("en", "DE")
    )

    reply = _post_json(
        _CYTIVA_API,
        {"productId": product_id.group(1).lower(), "language": language, "country": country},
        {},
    )
    if not isinstance(reply, dict):
        return {}
    data: dict = {}
    variants = reply.get("variants")
    variants = variants if isinstance(variants, list) else []
    if len(variants) == 1:
        variant = variants[0]
        data["item_name"] = _clean_text(str(variant.get("name") or reply.get("name") or ""))
        data["catalog_number"] = _clean_text(str(variant.get("productCode") or ""))
        data["pack_size"] = _clean_text(str(variant.get("packSize") or ""))
    else:
        data["item_name"] = _clean_text(str(reply.get("name") or ""))
        if variants:
            data["note"] = (
                f"{len(variants)} order variants on the page — "
                "add the catalog number for the size you need."
            )
    return data


def _amazon_from_url(parts: SplitResult) -> dict:
    match = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?=[/?#]|$)", parts.path, re.I)
    return {"catalog_number": match.group(1).upper()} if match else {}


def _amazon_from_page(page: str) -> dict:
    # Deliberately name-only: the page shows consumer prices, which differ from the
    # lab's Amazon Business pricing — prefilling them would suggest a wrong total.
    title = re.search(r'id="productTitle"[^>]*>\s*([^<]+)', page)
    return {"item_name": _clean_text(title.group(1))} if title else {}


PARSERS: tuple[VendorParser, ...] = (
    VendorParser(
        vendor_name="Merck (Sigma-Aldrich)",
        domain="sigmaaldrich",
        tlds=("com",),
        from_url=_sigma_from_url,
        from_api=_sigma_from_api,
        from_page=_sigma_from_page,
        aliases=("Merck", "Sigma-Aldrich", "Sigma Aldrich", "Sigma"),
    ),
    VendorParser(
        vendor_name="Carl Roth",
        domain="carlroth",
        tlds=("com", "de", "at", "ch", "fr", "it", "es"),
        from_url=_roth_from_url,
        from_page=_roth_from_page,
        aliases=("Roth", "Carl-Roth"),
    ),
    VendorParser(
        vendor_name="Fisher Scientific",
        domain="fishersci",
        tlds=(
            "com",
            "de",
            "at",
            "ch",
            "co.uk",
            "fr",
            "es",
            "it",
            "nl",
            "be",
            "dk",
            "se",
            "no",
            "fi",
            "ie",
            "pt",
            "ca",
        ),
        from_url=_fisher_from_url,
        from_page=_fisher_from_page,
        aliases=("Fisher", "Thermo Fisher", "Fisher Scientific"),
    ),
    VendorParser(
        vendor_name="VWR (Avantor)",
        domain="vwr",
        tlds=("com",),
        from_url=_vwr_from_url,
        aliases=("VWR", "Avantor"),
    ),
    VendorParser(
        vendor_name="Cytiva",
        domain="cytivalifesciences",
        tlds=("com",),
        from_url=_cytiva_from_url,
        from_api=_cytiva_from_api,
        aliases=("Cytiva", "GE Healthcare"),
    ),
    VendorParser(
        vendor_name="Amazon",
        domain="amazon",
        tlds=("de", "com", "co.uk", "fr", "it", "es", "nl", "se", "pl", "com.be", "ca"),
        from_url=_amazon_from_url,
        from_page=_amazon_from_page,
        aliases=("Amazon",),
        drop_fields=("unit_price", "currency", "pack_size"),
    ),
)
