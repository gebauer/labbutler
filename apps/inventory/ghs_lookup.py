"""CAS number → GHS classification lookup against PubChem.

Best-effort *suggestions* for the hazard pickers: two PUG requests resolve a CAS number
to a compound and pull its "GHS Classification" annotation (aggregated from vendor and
regulator SDS submissions). Every failure mode — network, rate limit, unknown CAS,
layout drift in PubChem's JSON — degrades to "no suggestion"; nothing here may ever
block a form.

Results are cached via the default Django cache (per-process LocMemCache today, which is
fine for a courtesy cache: the lookup is a manual button press and PubChem allows
5 req/s). Suggested codes are filtered to the seeded catalog (:mod:`.ghs`), so the
endpoint never proposes a code the picker doesn't offer.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import quote

from django.core.cache import cache

from .ghs import STATEMENTS_EN, canonical_code

CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")

_PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest"
_TIMEOUT_SECONDS = 5
_USER_AGENT = "LabButler/1.0 (+https://github.com/gebauer/labbutler)"

_POSITIVE_TTL = 30 * 24 * 3600  # found data is stable — keep for a month
_NEGATIVE_TTL = 24 * 3600  # failed/empty lookups may be transient — retry after a day
_CACHE_MISS = {"found": False}

# Below this share of ECHA C&L notifiers reporting a code, it is offered as a clickable
# extra instead of being auto-selected. Codes without percentage data (all P-statements,
# non-ECHA sources) are always auto-selected — there is nothing to judge them by.
SUGGEST_CUTOFF_PERCENT = 50.0

# PubChem pictogram display names -> official GHS pictogram codes. The matching SVGs
# live in static/img/ghs/<code>.svg.
PICTOGRAM_CODES = {
    "Explosive": "GHS01",
    "Flammable": "GHS02",
    "Oxidizer": "GHS03",
    "Compressed Gas": "GHS04",
    "Corrosive": "GHS05",
    "Acute Toxic": "GHS06",
    "Irritant": "GHS07",
    "Health Hazard": "GHS08",
    "Environmental Hazard": "GHS09",
}


@dataclass(frozen=True)
class GhsSuggestion:
    """What PubChem reports for a compound, reduced to what our models store."""

    signal_word: str = ""  # "", "warning" or "danger" (Item/Request choice values)
    hazard_codes: list[str] = field(default_factory=list)  # canonical H/EUH/P codes
    pictograms: list[str] = field(default_factory=list)  # display names, not stored
    # code -> % of ECHA C&L notifiers reporting it; only present where PubChem says so.
    percentages: dict[str, float] = field(default_factory=dict)
    # Codes from the EU harmonised classification (CLP Annex VI via Regulation (EC)
    # No 1272/2008), when PubChem carries that source. Legally binding in the EU —
    # preferred over notifier statistics for auto-selection.
    harmonized_codes: list[str] = field(default_factory=list)


def normalize_cas(raw: str) -> str:
    return (raw or "").strip()


def lookup_cas(cas: str) -> GhsSuggestion | None:
    """GHS data for a CAS number, or ``None`` if unknown/unreachable. Cached."""
    cas = normalize_cas(cas)
    if not CAS_RE.match(cas):
        return None
    cache_key = f"ghs-lookup:{cas}"
    cached = cache.get(cache_key)
    if cached is not None:
        if not cached["found"]:
            return None
        return GhsSuggestion(**cached["data"])

    suggestion = _fetch(cas)
    if suggestion is None:
        cache.set(cache_key, _CACHE_MISS, _NEGATIVE_TTL)
        return None
    cache.set(
        cache_key,
        {"found": True, "data": suggestion.__dict__},
        _POSITIVE_TTL,
    )
    return suggestion


def _fetch(cas: str) -> GhsSuggestion | None:
    cid = _cid_for_cas(cas)
    if cid is None:
        return None
    payload = _get_json(f"{_PUBCHEM}/pug_view/data/compound/{cid}/JSON?heading=GHS+Classification")
    if payload is None:
        return None
    return _parse_ghs(payload)


def _cid_for_cas(cas: str) -> int | None:
    """Resolve a CAS number to a PubChem compound ID (CAS numbers resolve as names)."""
    payload = _get_json(f"{_PUBCHEM}/pug/compound/name/{quote(cas)}/cids/JSON")
    try:
        return int(payload["IdentifierList"]["CID"][0])
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def _get_json(url: str) -> dict | None:
    """GET a JSON document; ``None`` on any transport, HTTP, or decoding problem.

    The single seam tests monkeypatch — everything above it is pure parsing.
    """
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


# --- PUG-View response parsing ----------------------------------------------------------

# Leading statement code of a line like "H225 (>99.9%): Highly flammable…", including
# combined statements ("H302+H312: …").
_LEADING_CODE_RE = re.compile(
    r"^\s*((?:EUH|H|P)\d{2,3}[A-Za-z]*(?:\+(?:EUH|H|P)?\d{2,3}[A-Za-z]*)*)"
)

# The notifier share directly after the code: "(95.2%)", "(>99.9%)", "(~55%)".
_PERCENT_RE = re.compile(r"^\s*\((?:[~>≥]\s*)?(\d+(?:\.\d+)?)\s*%\)")


def _parse_ghs(payload: dict) -> GhsSuggestion | None:
    record = payload.get("Record", {})
    infos = list(_walk_information(record))
    if not infos:
        return None

    sources = {
        ref.get("ReferenceNumber"): ref.get("SourceName", "") for ref in record.get("Reference", [])
    }
    signal_word = ""
    hazard_codes: list[str] = []
    pictograms: list[str] = []
    percentages: dict[str, float] = {}
    harmonized_codes: list[str] = []
    for info in infos:
        name = info.get("Name", "")
        strings = _strings_of(info)
        if name == "Signal":
            # Multiple SDS sources may disagree; the more severe word wins.
            words = {s.strip().lower() for s in strings}
            if "danger" in words:
                signal_word = "danger"
            elif "warning" in words and signal_word != "danger":
                signal_word = "warning"
        elif name == "GHS Hazard Statements":
            from_harmonized = "1272/2008" in sources.get(info.get("ReferenceNumber"), "")
            for line in strings:
                match = _LEADING_CODE_RE.match(line)
                if not match:
                    continue
                code = _add_code(hazard_codes, match.group(1))
                if code and from_harmonized and code not in harmonized_codes:
                    harmonized_codes.append(code)
                percent = _PERCENT_RE.match(line[match.end() :])
                if code and percent:
                    value = float(percent.group(1))
                    # Sources may repeat a code; keep the highest reported share.
                    percentages[code] = max(value, percentages.get(code, 0.0))
        elif name == "Precautionary Statement Codes":
            for line in strings:
                for token in line.split(","):
                    _add_code(hazard_codes, token)
        elif name == "Pictogram(s)":
            for markup in _markups_of(info):
                label = markup.get("Extra", "")
                if markup.get("Type") == "Icon" and label and label not in pictograms:
                    pictograms.append(label)

    if not (signal_word or hazard_codes or pictograms):
        return None
    return GhsSuggestion(
        signal_word=signal_word,
        hazard_codes=hazard_codes,
        pictograms=pictograms,
        percentages=percentages,
        harmonized_codes=harmonized_codes,
    )


def _add_code(codes: list[str], token: str) -> str | None:
    """Canonicalise a (possibly combined) code and collect it if the catalog knows it.

    Returns the canonical code when the catalog knows it (even if already collected),
    else ``None``.
    """
    code = "+".join(canonical_code(part) for part in token.strip().split("+") if part.strip())
    if not code or code not in STATEMENTS_EN:
        return None
    if code not in codes:
        codes.append(code)
    return code


def _walk_information(section: dict):
    """All Information entries under a PUG-View record, regardless of nesting."""
    yield from section.get("Information", [])
    for child in section.get("Section", []):
        yield from _walk_information(child)


def _strings_of(info: dict) -> list[str]:
    entries = info.get("Value", {}).get("StringWithMarkup", [])
    return [entry.get("String", "") for entry in entries]


def _markups_of(info: dict):
    for entry in info.get("Value", {}).get("StringWithMarkup", []):
        yield from entry.get("Markup", [])
