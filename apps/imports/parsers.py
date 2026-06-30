"""Pure parsing helpers for messy LabSuit export data.

Every function here is side-effect free and independently testable. They turn the raw
spreadsheet strings (prices, dates, locations, the comma-separated TAGS soup) into the
structured values the importer needs, and never touch the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

# --- Prices ---------------------------------------------------------------------------

# Currency symbols/codes seen in the real export, mapped to ISO codes.
_CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP"}
_CURRENCY_CODES = {"EUR", "USD", "GBP", "CHF"}
_PRICE_NUMBER_RE = re.compile(r"[0-9][0-9.,]*")


@dataclass(frozen=True)
class ParsedPrice:
    amount: Decimal | None
    currency: str = ""
    warning: str = ""


def _normalise_number(raw: str) -> Decimal | None:
    """Turn a human number (``1,249.00``, ``18,80``, ``235``) into a Decimal.

    Handles comma thousands separators and comma decimal separators by inspecting the
    positions of the last comma and dot.
    """
    raw = raw.strip()
    if not raw:
        return None
    last_dot = raw.rfind(".")
    last_comma = raw.rfind(",")
    if last_comma > last_dot:
        # Comma is the decimal separator (European): drop dots, comma -> dot.
        normalised = raw.replace(".", "").replace(",", ".")
    else:
        # Dot is the decimal separator: commas are thousands -> drop them.
        normalised = raw.replace(",", "")
    try:
        return Decimal(normalised)
    except InvalidOperation:
        return None


def parse_price(raw: object) -> ParsedPrice:
    """Parse the messy PRICE column into amount + ISO currency.

    Accepts plain numbers, prefix/suffix currency symbols and codes, comma thousands,
    and LabSuit's ``Money(109.00,EUR)`` wrapper. Returns amount=None with a warning when
    nothing numeric is present.
    """
    if raw is None:
        return ParsedPrice(None)
    text = str(raw).strip()
    if not text:
        return ParsedPrice(None)

    currency = ""

    # LabSuit's "Money(109.00,EUR)" wrapper.
    money = re.fullmatch(r"\s*Money\(\s*([^,]+?)\s*,\s*([A-Za-z]{3})\s*\)\s*", text)
    if money:
        amount = _normalise_number(money.group(1))
        return ParsedPrice(amount, money.group(2).upper())

    # Currency symbol anywhere.
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in text:
            currency = code
            text = text.replace(symbol, " ")
            break

    # Three-letter currency code as a prefix or suffix, possibly glued to the number
    # (e.g. "18.80EUR"), so no word boundary can be required.
    for code_match in re.finditer(r"[A-Za-z]{3}", text):
        if code_match.group(0).upper() in _CURRENCY_CODES:
            currency = currency or code_match.group(0).upper()
            text = (text[: code_match.start()] + " " + text[code_match.end() :]).strip()
            break

    number = _PRICE_NUMBER_RE.search(text)
    if not number:
        return ParsedPrice(None, currency, warning=f"unparseable price: {raw!r}")
    amount = _normalise_number(number.group(0))
    if amount is None:
        return ParsedPrice(None, currency, warning=f"unparseable price: {raw!r}")
    return ParsedPrice(amount, currency)


# --- Dates ----------------------------------------------------------------------------


def parse_european_date(raw: object) -> date | None:
    """Parse a European ``DD-MM-YYYY`` (or ``DD.MM.YYYY`` / ``DD/MM/YYYY``) date."""
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    match = re.fullmatch(r"(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})", text)
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


# --- Locations ------------------------------------------------------------------------


@dataclass(frozen=True)
class LocationLevel:
    name: str
    room_number: str = ""


_ROOM_PAREN_RE = re.compile(r"^(.*?)\s*\(([\w-]+)\)\s*$")


def parse_location_part(raw: object) -> LocationLevel | None:
    """Normalise one dirty location string into a name + optional room number.

    ``Storage room (376)`` -> ("Storage room", "376"); ``Room 376`` -> ("Room", "376");
    bare ``376`` -> ("Room 376", "376"). Returns None for blanks.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    paren = _ROOM_PAREN_RE.match(text)
    if paren:
        name = paren.group(1).strip() or f"Room {paren.group(2)}"
        return LocationLevel(name, paren.group(2))

    # A bare room number or "Room 376" -> normalise to a canonical "Room <n>" so the
    # three dirty spellings of the same room converge. Sub-locations like "Fridge 2"
    # are deliberately left untouched (no room number extracted).
    room = re.fullmatch(r"(?i)(?:room\s+)?(U?\d+)", text)
    if room:
        number = room.group(1)
        return LocationLevel(f"Room {number}", number)

    return LocationLevel(text)


def parse_location_path(*parts: object) -> list[LocationLevel]:
    """Build the ordered, blank-skipping location hierarchy from up to three columns."""
    levels = []
    for part in parts:
        level = parse_location_part(part)
        if level is not None:
            levels.append(level)
    return levels


# --- TAGS soup ------------------------------------------------------------------------

_SIGNAL_WORDS = {
    "achtung": "warning",
    "warnung": "warning",
    "warning": "warning",
    "gefahr": "danger",
    "danger": "danger",
}
_NON_HAZARD_PHRASES = {
    "no hazard statements",
    "no information on hazard statements",
}
# A single GHS code: H/EUH/P + digits + optional letter suffix (H350i, H360FD).
_HAZARD_CODE_RE = re.compile(r"^(EUH|H|P)\d{2,3}[A-Za-z]{0,3}$", re.IGNORECASE)
# A token may bundle several codes joined by + or - (H315+H319, P305-P351-P338).
_COMBO_SPLIT_RE = re.compile(r"\s*[+\-]\s*")


@dataclass
class ParsedTags:
    hazard_codes: list[str] = field(default_factory=list)
    signal_word: str = ""
    wgk: str = ""
    storage_class: str = ""
    tags: list[str] = field(default_factory=list)


def _extract_hazard_codes(token: str) -> list[str] | None:
    """Return the GHS codes in a token if every part is a code, else None."""
    parts = _COMBO_SPLIT_RE.split(token)
    codes = []
    for part in parts:
        part = part.strip()
        if not _HAZARD_CODE_RE.match(part):
            return None
        codes.append(part.upper())
    return codes or None


def parse_tags(raw: object) -> ParsedTags:
    """Split LabSuit's comma-separated TAGS into structured hazard data + freeform tags.

    Pulls out GHS H/EUH/P codes (including ``H315+H319`` combinations), the signal word
    (normalised to warning/danger), WGK and Lagerklasse (LK), and leaves genuine
    leftovers (years, project names) as tags.
    """
    result = ParsedTags()
    if raw is None:
        return result

    for token in str(raw).split(","):
        token = token.strip()
        if not token:
            continue

        lowered = token.lower()
        if lowered in _NON_HAZARD_PHRASES:
            continue

        if lowered in _SIGNAL_WORDS:
            # Danger outranks warning if both appear.
            word = _SIGNAL_WORDS[lowered]
            if word == "danger" or not result.signal_word:
                result.signal_word = word
            continue

        if lowered.startswith("wgk"):
            value = token[3:].strip()
            if value.lower() not in ("", "n/a", "nwg"):
                result.wgk = value
            continue

        if lowered.startswith("lk"):
            value = token[2:].strip()
            if value.lower() not in ("", "n/a"):
                result.storage_class = value
            continue

        codes = _extract_hazard_codes(token)
        if codes is not None:
            for code in codes:
                if code not in result.hazard_codes:
                    result.hazard_codes.append(code)
            continue

        result.tags.append(token)

    return result


# --- Amount in stock ------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedAmount:
    value: Decimal | None
    warning: str = ""


def parse_amount_in_stock(raw: object) -> ParsedAmount:
    """Parse the AMOUNT_IN_STOCK column, which may be junk (``empty``, ``4 Kartons``)."""
    if raw is None:
        return ParsedAmount(None)
    text = str(raw).strip()
    if not text or text.lower() == "empty":
        return ParsedAmount(None)
    number = re.match(r"[0-9][0-9.,]*", text)
    if not number:
        return ParsedAmount(None, warning=f"non-numeric amount: {raw!r}")
    value = _normalise_number(number.group(0))
    # Trailing units like "4 Kartons" -> keep the number but flag for review.
    if number.group(0) != text:
        return ParsedAmount(value, warning=f"amount has extra text: {raw!r}")
    return ParsedAmount(value)
