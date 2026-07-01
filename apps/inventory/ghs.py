"""Canonical GHS / EU-CLP hazard-statement catalog.

The statement text belongs to the *code*, not to any compound: an item links to the
shared :class:`~apps.inventory.models.HazardStatement` rows seeded from this catalog, so
hovering a code anywhere shows the one general sentence for that number.

Only English (:data:`STATEMENTS_EN`) is provided today. Other languages plug in the same
way: add e.g. ``STATEMENTS_DE`` here and seed the matching ``HazardStatement.text_de``
column in a follow-up migration — no schema or code changes needed.

This module is intentionally free of Django imports so the pure spreadsheet parsers can
reuse :func:`canonical_code`.
"""
# Official statement wording is quoted verbatim; long lines are inherent to the data.
# ruff: noqa: E501

from __future__ import annotations

import re

# --- Code normalisation ---------------------------------------------------------------

_CODE_RE = re.compile(r"^\s*(EUH|H|P)(\d{2,3})([A-Za-z]*)\s*$", re.IGNORECASE)


def canonical_code(raw: str) -> str:
    """Normalise a single GHS code to its canonical casing.

    Suffix casing carries meaning and is code-specific (``H350i`` but ``EUH201A``), so the
    catalog itself is the source of truth: the prefix is upper-cased, the H360/H361 letters
    are ordered F before D, and a single-case suffix is snapped to the catalog's spelling
    (fixing blindly upper-cased legacy codes like ``H350I``). An already-mixed-case suffix
    (e.g. ``H360Fd``) is trusted as-is. Non-matching input is returned upper-cased.
    """
    match = _CODE_RE.match(raw or "")
    if not match:
        return (raw or "").strip().upper()
    prefix, digits, suffix = match.group(1).upper(), match.group(2), match.group(3)
    if not suffix:
        return f"{prefix}{digits}"

    # Reproductive-tox combos (H360/H361): each letter's case (F/D = fertility/unborn,
    # upper = presumed, lower = suspected) carries meaning, so match on the set of signals
    # rather than order — H360Df, H360fD and H360DF all resolve unambiguously.
    if prefix == "H" and digits in ("360", "361") and all(c in "FDfd" for c in suffix):
        signature = (digits, frozenset((c.upper(), c.isupper()) for c in suffix))
        if signature in _REPRODUCTIVE_BY_SIGNATURE:
            return _REPRODUCTIVE_BY_SIGNATURE[signature]

    # Snap a single-/mixed-case suffix to the catalog spelling (fixes H350I, EUH201a).
    known = _CANONICAL_BY_UPPER.get(f"{prefix}{digits}{suffix}".upper())
    if known:
        return known
    if prefix == "H" and digits == "360":
        return f"{prefix}{digits}{suffix.upper()}"
    if prefix == "H" and digits == "361":
        return f"{prefix}{digits}{suffix.lower()}"
    return f"{prefix}{digits}{suffix}"


def kind_for(code: str) -> str:
    """Map a code to a :class:`HazardStatement.Kind` value (``H`` / ``EUH`` / ``P``)."""
    upper = code.upper()
    if upper.startswith("EUH"):
        return "EUH"
    if upper.startswith("P"):
        return "P"
    return "H"


# --- English statement catalog --------------------------------------------------------
# Canonical code -> official English text (CLP Annex III/IV + GHS). Combined statements
# are included for completeness; the TAGS parser splits real data into single codes.

STATEMENTS_EN: dict[str, str] = {
    # Physical hazards (H2xx)
    "H200": "Unstable explosive",
    "H201": "Explosive; mass explosion hazard",
    "H202": "Explosive; severe projection hazard",
    "H203": "Explosive; fire, blast or projection hazard",
    "H204": "Fire or projection hazard",
    "H205": "May mass explode in fire",
    "H206": "Fire, blast or projection hazard; increased risk of explosion if desensitising agent is reduced",
    "H207": "Fire or projection hazard; increased risk of explosion if desensitising agent is reduced",
    "H208": "Fire hazard; increased risk of explosion if desensitising agent is reduced",
    "H220": "Extremely flammable gas",
    "H221": "Flammable gas",
    "H222": "Extremely flammable aerosol",
    "H223": "Flammable aerosol",
    "H224": "Extremely flammable liquid and vapour",
    "H225": "Highly flammable liquid and vapour",
    "H226": "Flammable liquid and vapour",
    "H228": "Flammable solid",
    "H229": "Pressurised container: may burst if heated",
    "H230": "May react explosively even in the absence of air",
    "H231": "May react explosively even in the absence of air at elevated pressure and/or temperature",
    "H232": "May ignite spontaneously if exposed to air",
    "H240": "Heating may cause an explosion",
    "H241": "Heating may cause a fire or explosion",
    "H242": "Heating may cause a fire",
    "H250": "Catches fire spontaneously if exposed to air",
    "H251": "Self-heating; may catch fire",
    "H252": "Self-heating in large quantities; may catch fire",
    "H260": "In contact with water releases flammable gases which may ignite spontaneously",
    "H261": "In contact with water releases flammable gases",
    "H270": "May cause or intensify fire; oxidiser",
    "H271": "May cause fire or explosion; strong oxidiser",
    "H272": "May intensify fire; oxidiser",
    "H280": "Contains gas under pressure; may explode if heated",
    "H281": "Contains refrigerated gas; may cause cryogenic burns or injury",
    "H290": "May be corrosive to metals",
    # Health hazards (H3xx)
    "H300": "Fatal if swallowed",
    "H301": "Toxic if swallowed",
    "H302": "Harmful if swallowed",
    "H303": "May be harmful if swallowed",
    "H304": "May be fatal if swallowed and enters airways",
    "H305": "May be harmful if swallowed and enters airways",
    "H310": "Fatal in contact with skin",
    "H311": "Toxic in contact with skin",
    "H312": "Harmful in contact with skin",
    "H313": "May be harmful in contact with skin",
    "H314": "Causes severe skin burns and eye damage",
    "H315": "Causes skin irritation",
    "H316": "Causes mild skin irritation",
    "H317": "May cause an allergic skin reaction",
    "H318": "Causes serious eye damage",
    "H319": "Causes serious eye irritation",
    "H320": "Causes eye irritation",
    "H330": "Fatal if inhaled",
    "H331": "Toxic if inhaled",
    "H332": "Harmful if inhaled",
    "H333": "May be harmful if inhaled",
    "H334": "May cause allergy or asthma symptoms or breathing difficulties if inhaled",
    "H335": "May cause respiratory irritation",
    "H336": "May cause drowsiness or dizziness",
    "H340": "May cause genetic defects",
    "H341": "Suspected of causing genetic defects",
    "H350": "May cause cancer",
    "H350i": "May cause cancer by inhalation",
    "H351": "Suspected of causing cancer",
    "H360": "May damage fertility or the unborn child",
    "H360F": "May damage fertility",
    "H360D": "May damage the unborn child",
    "H360FD": "May damage fertility. May damage the unborn child",
    "H360Fd": "May damage fertility. Suspected of damaging the unborn child",
    "H360Df": "May damage the unborn child. Suspected of damaging fertility",
    "H361": "Suspected of damaging fertility or the unborn child",
    "H361f": "Suspected of damaging fertility",
    "H361d": "Suspected of damaging the unborn child",
    "H361fd": "Suspected of damaging fertility. Suspected of damaging the unborn child",
    "H362": "May cause harm to breast-fed children",
    "H370": "Causes damage to organs",
    "H371": "May cause damage to organs",
    "H372": "Causes damage to organs through prolonged or repeated exposure",
    "H373": "May cause damage to organs through prolonged or repeated exposure",
    # Combined health hazards
    "H300+H310": "Fatal if swallowed or in contact with skin",
    "H300+H330": "Fatal if swallowed or if inhaled",
    "H310+H330": "Fatal in contact with skin or if inhaled",
    "H300+H310+H330": "Fatal if swallowed, in contact with skin or if inhaled",
    "H301+H311": "Toxic if swallowed or in contact with skin",
    "H301+H331": "Toxic if swallowed or if inhaled",
    "H311+H331": "Toxic in contact with skin or if inhaled",
    "H301+H311+H331": "Toxic if swallowed, in contact with skin or if inhaled",
    "H302+H312": "Harmful if swallowed or in contact with skin",
    "H302+H332": "Harmful if swallowed or if inhaled",
    "H312+H332": "Harmful in contact with skin or if inhaled",
    "H302+H312+H332": "Harmful if swallowed, in contact with skin or if inhaled",
    # Environmental hazards (H4xx)
    "H400": "Very toxic to aquatic life",
    "H401": "Toxic to aquatic life",
    "H402": "Harmful to aquatic life",
    "H410": "Very toxic to aquatic life with long lasting effects",
    "H411": "Toxic to aquatic life with long lasting effects",
    "H412": "Harmful to aquatic life with long lasting effects",
    "H413": "May cause long lasting harmful effects to aquatic life",
    "H420": "Harms public health and the environment by destroying ozone in the upper atmosphere",
    # EU-specific hazard statements (EUH)
    "EUH001": "Explosive when dry",
    "EUH014": "Reacts violently with water",
    "EUH018": "In use may form flammable/explosive vapour-air mixture",
    "EUH019": "May form explosive peroxides",
    "EUH029": "Contact with water liberates toxic gas",
    "EUH031": "Contact with acids liberates toxic gas",
    "EUH032": "Contact with acids liberates very toxic gas",
    "EUH044": "Risk of explosion if heated under confinement",
    "EUH059": "Hazardous to the ozone layer",
    "EUH066": "Repeated exposure may cause skin dryness or cracking",
    "EUH070": "Toxic by eye contact",
    "EUH071": "Corrosive to the respiratory tract",
    "EUH201": "Contains lead. Should not be used on surfaces liable to be chewed or sucked by children",
    "EUH201A": "Warning! Contains lead",
    "EUH203": "Contains chromium (VI). May produce an allergic reaction",
    "EUH204": "Contains isocyanates. May produce an allergic reaction",
    "EUH205": "Contains epoxy constituents. May produce an allergic reaction",
    "EUH206": "Warning! Do not use together with other products. May release dangerous gases (chlorine)",
    "EUH207": "Warning! Contains cadmium. Dangerous fumes are formed during use. See information supplied by the manufacturer. Comply with the safety instructions",
    "EUH208": "Contains (name of sensitising substance). May produce an allergic reaction",
    "EUH209": "Can become highly flammable in use",
    "EUH209A": "Can become flammable in use",
    "EUH210": "Safety data sheet available on request",
    "EUH401": "To avoid risks to human health and the environment, comply with the instructions for use",
    # Precautionary — general (P1xx)
    "P101": "If medical advice is needed, have product container or label at hand",
    "P102": "Keep out of reach of children",
    "P103": "Read carefully and follow all instructions",
    # Precautionary — prevention (P2xx)
    "P201": "Obtain special instructions before use",
    "P202": "Do not handle until all safety precautions have been read and understood",
    "P210": "Keep away from heat, hot surfaces, sparks, open flames and other ignition sources. No smoking",
    "P211": "Do not spray on an open flame or other ignition source",
    "P212": "Avoid heating under confinement or reduction of the desensitising agent",
    "P220": "Keep away from clothing and other combustible materials",
    "P222": "Do not allow contact with air",
    "P223": "Do not allow contact with water",
    "P230": "Keep wetted with appropriate material",
    "P231": "Handle and store contents under inert gas",
    "P232": "Protect from moisture",
    "P233": "Keep container tightly closed",
    "P234": "Keep only in original packaging",
    "P235": "Keep cool",
    "P240": "Ground and bond container and receiving equipment",
    "P241": "Use explosion-proof electrical/ventilating/lighting equipment",
    "P242": "Use non-sparking tools",
    "P243": "Take precautionary measures against static discharge",
    "P244": "Keep valves and fittings free from oil and grease",
    "P250": "Do not subject to grinding/shock/friction",
    "P251": "Do not pierce or burn, even after use",
    "P260": "Do not breathe dust/fume/gas/mist/vapours/spray",
    "P261": "Avoid breathing dust/fume/gas/mist/vapours/spray",
    "P262": "Do not get in eyes, on skin, or on clothing",
    "P263": "Avoid contact during pregnancy and while nursing",
    "P264": "Wash thoroughly after handling",
    "P270": "Do not eat, drink or smoke when using this product",
    "P271": "Use only outdoors or in a well-ventilated area",
    "P272": "Contaminated work clothing should not be allowed out of the workplace",
    "P273": "Avoid release to the environment",
    "P280": "Wear protective gloves/protective clothing/eye protection/face protection",
    "P281": "Use personal protective equipment as required",
    "P282": "Wear cold insulating gloves and either face shield or eye protection",
    "P283": "Wear fire resistant or flame retardant clothing",
    "P284": "In case of inadequate ventilation wear respiratory protection",
    # Precautionary — response (P3xx)
    "P301": "IF SWALLOWED:",
    "P302": "IF ON SKIN:",
    "P303": "IF ON SKIN (or hair):",
    "P304": "IF INHALED:",
    "P305": "IF IN EYES:",
    "P306": "IF ON CLOTHING:",
    "P308": "IF exposed or concerned:",
    "P310": "Immediately call a POISON CENTER or doctor/physician",
    "P311": "Call a POISON CENTER or doctor/physician",
    "P312": "Call a POISON CENTER or doctor/physician if you feel unwell",
    "P313": "Get medical advice/attention",
    "P314": "Get medical advice/attention if you feel unwell",
    "P315": "Get immediate medical advice/attention",
    "P320": "Specific treatment is urgent (see supplemental first aid instructions on this label)",
    "P321": "Specific treatment (see supplemental first aid instructions on this label)",
    "P330": "Rinse mouth",
    "P331": "Do NOT induce vomiting",
    "P332": "If skin irritation occurs:",
    "P333": "If skin irritation or rash occurs:",
    "P334": "Immerse in cool water or wrap in wet bandages",
    "P335": "Brush off loose particles from skin",
    "P336": "Thaw frosted parts with lukewarm water. Do not rub affected area",
    "P337": "If eye irritation persists:",
    "P338": "Remove contact lenses, if present and easy to do. Continue rinsing",
    "P340": "Remove person to fresh air and keep comfortable for breathing",
    "P342": "If experiencing respiratory symptoms:",
    "P351": "Rinse cautiously with water for several minutes",
    "P352": "Wash with plenty of water",
    "P353": "Rinse skin with water or shower",
    "P360": "Rinse immediately contaminated clothing and skin with plenty of water before removing clothes",
    "P361": "Take off immediately all contaminated clothing",
    "P362": "Take off contaminated clothing",
    "P363": "Wash contaminated clothing before reuse",
    "P364": "And wash it before reuse",
    "P370": "In case of fire:",
    "P371": "In case of major fire and large quantities:",
    "P372": "Explosion risk in case of fire",
    "P373": "DO NOT fight fire when fire reaches explosives",
    "P375": "Fight fire remotely due to the risk of explosion",
    "P376": "Stop leak if safe to do so",
    "P377": "Leaking gas fire: Do not extinguish, unless leak can be stopped safely",
    "P378": "Use appropriate media to extinguish",
    "P380": "Evacuate area",
    "P381": "In case of leakage, eliminate all ignition sources",
    "P390": "Absorb spillage to prevent material damage",
    "P391": "Collect spillage",
    # Precautionary — storage (P4xx)
    "P401": "Store in accordance with local/regional/national/international regulations",
    "P402": "Store in a dry place",
    "P403": "Store in a well-ventilated place",
    "P404": "Store in a closed container",
    "P405": "Store locked up",
    "P406": "Store in a corrosion resistant container with a resistant inner liner",
    "P407": "Maintain air gap between stacks or pallets",
    "P410": "Protect from sunlight",
    "P411": "Store at temperatures not exceeding the stated value",
    "P412": "Do not expose to temperatures exceeding 50 °C/122 °F",
    "P413": "Store bulk masses greater than the stated weight at temperatures not exceeding the stated value",
    "P420": "Store separately",
    # Precautionary — disposal (P5xx)
    "P501": "Dispose of contents/container in accordance with local/regional/national/international regulations",
    "P502": "Refer to manufacturer or supplier for information on recovery or recycling",
    "P503": "Refer to manufacturer/supplier for information on disposal/recovery/recycling",
    # Combined precautionary statements (common)
    "P235+P410": "Keep cool. Protect from sunlight",
    "P301+P310": "IF SWALLOWED: Immediately call a POISON CENTER or doctor/physician",
    "P301+P312": "IF SWALLOWED: Call a POISON CENTER or doctor/physician if you feel unwell",
    "P301+P330+P331": "IF SWALLOWED: Rinse mouth. Do NOT induce vomiting",
    "P302+P334": "IF ON SKIN: Immerse in cool water or wrap in wet bandages",
    "P302+P352": "IF ON SKIN: Wash with plenty of water",
    "P303+P361+P353": "IF ON SKIN (or hair): Take off immediately all contaminated clothing. Rinse skin with water or shower",
    "P304+P340": "IF INHALED: Remove person to fresh air and keep comfortable for breathing",
    "P305+P351+P338": "IF IN EYES: Rinse cautiously with water for several minutes. Remove contact lenses, if present and easy to do. Continue rinsing",
    "P306+P360": "IF ON CLOTHING: Rinse immediately contaminated clothing and skin with plenty of water before removing clothes",
    "P308+P311": "IF exposed or concerned: Call a POISON CENTER or doctor/physician",
    "P308+P313": "IF exposed or concerned: Get medical advice/attention",
    "P332+P313": "If skin irritation occurs: Get medical advice/attention",
    "P333+P313": "If skin irritation or rash occurs: Get medical advice/attention",
    "P337+P313": "If eye irritation persists: Get medical advice/attention",
    "P342+P311": "If experiencing respiratory symptoms: Call a POISON CENTER or doctor/physician",
    "P362+P364": "Take off contaminated clothing and wash it before reuse",
    "P370+P378": "In case of fire: Use appropriate media to extinguish",
    "P403+P233": "Store in a well-ventilated place. Keep container tightly closed",
    "P403+P235": "Store in a well-ventilated place. Keep cool",
    "P410+P412": "Protect from sunlight. Do not expose to temperatures exceeding 50 °C/122 °F",
}

# Upper-cased code -> canonical spelling, so canonical_code() can repair legacy casing.
# Insertion order means the presumed variant wins an ambiguous key (H360FD over H360Fd).
_CANONICAL_BY_UPPER: dict[str, str] = {}
for _code in STATEMENTS_EN:
    _CANONICAL_BY_UPPER.setdefault(_code.upper(), _code)

# H360/H361 combos indexed by their order-free set of (letter, is-presumed) signals.
_REPRODUCTIVE_BY_SIGNATURE: dict[tuple[str, frozenset], str] = {}
for _code in STATEMENTS_EN:
    _match = _CODE_RE.match(_code)
    if _match is None:  # skip combined "+"-joined statements
        continue
    _digits, _suffix = _match.group(2), _match.group(3)
    if _digits in ("360", "361") and _suffix and all(c in "FDfd" for c in _suffix):
        _signature = (_digits, frozenset((c.upper(), c.isupper()) for c in _suffix))
        _REPRODUCTIVE_BY_SIGNATURE[_signature] = _code
