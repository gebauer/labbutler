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

# --- Recommended precautionary statements per hazard statement --------------------------
# H-code -> P-statements the UN GHS assigns to that hazard class/category (prevention,
# response, storage, disposal columns merged; categories of one code unioned). Extracted
# from PubChem's GHS classification summary (https://pubchem.ncbi.nlm.nih.gov/ghs/),
# which mirrors the official tables. Used to rank looked-up P-statement suggestions —
# never to block anything.

PRECAUTIONARY_FOR: dict[str, tuple[str, ...]] = {
    "H200": ("P201", "P202", "P281", "P372", "P373", "P380", "P401", "P501"),
    "H201": ("P210", "P230", "P240", "P250", "P280", "P370+P380", "P372", "P373", "P401", "P501"),
    "H202": ("P210", "P230", "P240", "P250", "P280", "P370+P380", "P372", "P373", "P401", "P501"),
    "H203": ("P210", "P230", "P240", "P250", "P280", "P370+P380", "P372", "P373", "P401", "P501"),
    "H204": (
        "P203",
        "P210",
        "P230",
        "P234",
        "P236",
        "P240",
        "P250",
        "P280",
        "P370+P372+P380+P373",
        "P401",
        "P503",
        "P370+P380+P375",
    ),
    "H205": ("P210", "P230", "P240", "P250", "P280", "P370+P380", "P372", "P373", "P401", "P501"),
    "H206": ("P210", "P212", "P230", "P233", "P280", "P370+P380+P375", "P401", "P501"),
    "H207": ("P210", "P212", "P230", "P233", "P280", "P370+P380+P375", "P401", "P501"),
    "H208": ("P210", "P212", "P230", "P233", "P280", "P371+P380+P375", "P401", "P501"),
    "H209": (
        "P230",
        "P210",
        "P240",
        "P250",
        "P280",
        "P370+P372+P380+P373",
        "P401",
        "P503",
        "P203",
        "P234",
        "P236",
    ),
    "H210": ("P230", "P210", "P240", "P250", "P280", "P370+P372+P380+P373", "P401", "P503"),
    "H211": ("P230", "P210", "P240", "P250", "P280", "P370+P372+P380+P373", "P401", "P504"),
    "H220": ("P203", "P210", "P222", "P280", "P377", "P381", "P403"),
    "H221": ("P210", "P377", "P381", "P403"),
    "H222": ("P210", "P211", "P251", "P410+P412"),
    "H223": ("P210", "P211", "P251", "P410+P412"),
    "H224": (
        "P210",
        "P233",
        "P240",
        "P241",
        "P242",
        "P243",
        "P280",
        "P303+P361+P353",
        "P370+P378",
        "P403+P235",
        "P501",
    ),
    "H225": (
        "P210",
        "P233",
        "P240",
        "P241",
        "P242",
        "P243",
        "P280",
        "P303+P361+P353",
        "P370+P378",
        "P403+P235",
        "P501",
    ),
    "H226": (
        "P210",
        "P233",
        "P240",
        "P241",
        "P242",
        "P243",
        "P280",
        "P303+P361+P353",
        "P370+P378",
        "P403+P235",
        "P501",
    ),
    "H227": ("P210", "P280", "P370+P378", "P403", "P501"),
    "H228": ("P210", "P240", "P241", "P280", "P370+P378"),
    "H229": ("P210", "P211", "P251", "P410+P412"),
    "H230": ("P203", "P210", "P337", "P381", "P403"),
    "H231": ("P203", "P210", "P337", "P381", "P403"),
    "H232": ("P210", "P222", "P280", "P377", "P381", "P403"),
    "H240": (
        "P210",
        "P234",
        "P235",
        "P240",
        "P280",
        "P370+P372+P380+P373",
        "P403",
        "P410",
        "P411",
        "P420",
        "P501",
    ),
    "H241": ("P210", "P234", "P235", "P240", "P280", "P403", "P410", "P411", "P420", "P501"),
    "H242": (
        "P210",
        "P234",
        "P235",
        "P240",
        "P280",
        "P370+P378",
        "P403",
        "P410",
        "P411",
        "P420",
        "P501",
    ),
    "H250": ("P210", "P222", "P231", "P233", "P280", "P302+P334", "P370+P378", "P302+P335+P334"),
    "H251": ("P235", "P280", "P407", "P410", "P413", "P420"),
    "H252": ("P235", "P280", "P407", "P410", "P413", "P420"),
    "H260": ("P223", "P231+P232", "P280", "P302+P335+P334", "P370+P378", "P402+P404", "P501"),
    "H261": ("P223", "P231+P232", "P280", "P302+P335+P334", "P370+P378", "P402+P404", "P501"),
    "H270": ("P220", "P244", "P370+P376", "P403"),
    "H271": (
        "P210",
        "P220",
        "P280",
        "P283",
        "P306+P360",
        "P371+P380+P375",
        "P370+P378",
        "P420",
        "P501",
    ),
    "H272": ("P210", "P220", "P280", "P370+P378", "P501"),
    "H280": ("P410+P403"),
    "H281": ("P282", "P336+P317", "P403"),
    "H282": ("P210", "P211", "P370+P378", "P376", "P381", "P410+P403"),
    "H283": ("P210", "P211", "P370+P378", "P376", "P381", "P410+P403"),
    "H284": ("P210", "P376", "P410+P403"),
    "H290": ("P234", "P390", "P406"),
    "H300": ("P264", "P270", "P301+P316", "P321", "P330", "P405", "P501"),
    "H301": ("P264", "P270", "P301+P316", "P321", "P330", "P405", "P501"),
    "H302": ("P264", "P270", "P301+P317", "P330", "P501"),
    "H303": ("P301+P317"),
    "H304": ("P301+P316", "P331", "P405", "P501"),
    "H305": ("P301+P316", "P331", "P405", "P501"),
    "H310": (
        "P262",
        "P264",
        "P270",
        "P280",
        "P302+P352",
        "P316",
        "P321",
        "P361+P364",
        "P405",
        "P501",
    ),
    "H311": (
        "P262",
        "P264",
        "P270",
        "P280",
        "P302+P352",
        "P316",
        "P321",
        "P361+P364",
        "P405",
        "P501",
    ),
    "H312": ("P280", "P302+P352", "P317", "P321", "P362+P364", "P501"),
    "H313": ("P302+P317"),
    "H314": (
        "P260",
        "P264",
        "P280",
        "P301+P330+P331",
        "P302+P361+P354",
        "P363",
        "P304+P340",
        "P316",
        "P321",
        "P305+P354+P338",
        "P405",
        "P501",
    ),
    "H315": ("P264", "P280", "P302+P352", "P321", "P332+P317", "P362+P364"),
    "H316": ("P332+P317"),
    "H317": ("P261", "P272", "P280", "P302+P352", "P333+P317", "P321", "P362+P364", "P501"),
    "H318": ("P264+P265", "P280", "P305+P354+P338", "P317"),
    "H319": ("P264+P265", "P280", "P305+P351+P338", "P337+P317"),
    "H320": ("P264+P265", "P305+P351+P338", "P337+P317"),
    "H330": ("P260", "P271", "P284", "P304+P340", "P316", "P320", "P403+P233", "P405", "P501"),
    "H331": ("P261", "P271", "P304+P340", "P316", "P321", "P403+P233", "P405", "P501"),
    "H332": ("P261", "P271", "P304+P340", "P317"),
    "H333": ("P304+P317"),
    "H334": ("P233", "P260", "P271", "P284", "P304+P340", "P342+P316", "P403", "P501"),
    "H335": ("P261", "P271", "P304+P340", "P319", "P403+P233", "P405", "P501"),
    "H336": ("P261", "P271", "P304+P340", "P319", "P403+P233", "P405", "P501"),
    "H340": ("P203", "P280", "P318", "P405", "P501"),
    "H341": ("P203", "P280", "P318", "P405", "P501"),
    "H350": ("P203", "P280", "P318", "P405", "P501"),
    "H351": ("P203", "P280", "P318", "P405", "P501"),
    "H360": ("P203", "P280", "P318", "P405", "P501"),
    "H361": ("P203", "P280", "P318", "P405", "P501"),
    "H362": ("P203", "P260", "P263", "P264", "P270", "P318"),
    "H370": ("P260", "P264", "P270", "P308+P316", "P321", "P405", "P501"),
    "H371": ("P260", "P264", "P270", "P308+P316", "P405", "P501"),
    "H372": ("P260", "P264", "P270", "P319", "P501"),
    "H373": ("P260", "P319", "P501"),
    "H400": ("P273", "P391", "P501"),
    "H401": ("P273", "P501"),
    "H402": ("P273", "P501"),
    "H410": ("P273", "P391", "P501"),
    "H411": ("P273", "P391", "P501"),
    "H412": ("P273", "P501"),
    "H413": ("P273", "P501"),
    "H420": ("P502"),
    "H421": ("P502"),
}

# The UN renumbered several response statements across GHS revisions (e.g. rev. 9/10:
# P305+P351+P338 -> P305+P354+P338, P310/P311 -> P316), while EU CLP data still uses the
# older codes. Both generations map onto one bucket so recommendations match either.
_P_EQUIVALENTS: dict[str, str] = {
    "P302": "P302",
    "P303": "P302",  # IF ON SKIN (or hair)
    "P351": "P353",
    "P352": "P353",
    "P354": "P353",  # rinse/wash with water
    "P310": "P310",
    "P311": "P310",
    "P316": "P310",  # immediate medical help
    "P312": "P313",
    "P314": "P313",
    "P315": "P313",  # get medical advice
    "P317": "P313",
    "P318": "P313",
    "P319": "P313",
    "P332": "P332",
    "P333": "P332",  # if skin irritation
    "P337": "P337",
    "P338": "P338",
}


def _p_signal_parts(code: str) -> set[str]:
    """A P-code's constituent statements, folded onto revision-independent buckets."""
    return {_P_EQUIVALENTS.get(part, part) for part in code.split("+")}


def recommended_p_parts(h_codes: list[str]) -> set[str] | None:
    """Bucketed P-statement parts the GHS recommends for the given H-codes.

    ``None`` when no given code has recommendation data (unknown or EUH-only input) —
    callers should fail open and treat every P-statement as plausible then.
    """
    parts: set[str] = set()
    found_any = False
    for h_code in h_codes:
        for single in h_code.split("+"):
            recommended = PRECAUTIONARY_FOR.get(single)
            if not recommended:
                continue
            found_any = True
            for p_code in recommended:
                parts |= _p_signal_parts(p_code)
    return parts if found_any else None


def is_recommended_p(p_code: str, parts: set[str]) -> bool:
    """Whether a (possibly combined) P-code shares any part with the recommended set."""
    return bool(_p_signal_parts(p_code) & parts)


# --- Pictograms per hazard statement ----------------------------------------------------
# H-code -> GHS pictogram codes (GHS01..GHS09), from the same official table as
# PRECAUTIONARY_FOR. Codes without an entry (all P/EUH, some H) carry no pictogram.
# The SVGs live in static/img/ghs/<code>.svg.

PICTOGRAMS_FOR: dict[str, tuple[str, ...]] = {
    "H200": ("GHS01",),
    "H201": ("GHS01",),
    "H202": ("GHS01",),
    "H203": ("GHS01",),
    "H204": (
        "GHS01",
        "GHS07",
    ),
    "H205": ("GHS02",),
    "H206": ("GHS02",),
    "H207": ("GHS02",),
    "H208": ("GHS02",),
    "H209": ("GHS01",),
    "H210": ("GHS01",),
    "H211": ("GHS01",),
    "H220": ("GHS02",),
    "H221": ("GHS02",),
    "H222": ("GHS02",),
    "H223": ("GHS02",),
    "H224": ("GHS02",),
    "H225": ("GHS02",),
    "H226": ("GHS02",),
    "H228": ("GHS02",),
    "H229": ("GHS02",),
    "H230": ("GHS02",),
    "H231": ("GHS02",),
    "H232": ("GHS02",),
    "H240": ("GHS01",),
    "H241": (
        "GHS01",
        "GHS02",
    ),
    "H242": ("GHS02",),
    "H250": ("GHS02",),
    "H251": ("GHS02",),
    "H252": ("GHS02",),
    "H260": ("GHS02",),
    "H261": ("GHS02",),
    "H270": ("GHS03",),
    "H271": ("GHS03",),
    "H272": ("GHS03",),
    "H280": ("GHS04",),
    "H281": ("GHS04",),
    "H282": (
        "GHS02",
        "GHS04",
    ),
    "H283": (
        "GHS02",
        "GHS04",
    ),
    "H284": ("GHS04",),
    "H290": ("GHS05",),
    "H300": ("GHS06",),
    "H301": ("GHS06",),
    "H302": ("GHS07",),
    "H304": ("GHS08",),
    "H305": ("GHS08",),
    "H310": ("GHS06",),
    "H311": ("GHS06",),
    "H312": ("GHS07",),
    "H314": ("GHS05",),
    "H315": ("GHS07",),
    "H317": ("GHS07",),
    "H318": ("GHS05",),
    "H319": ("GHS07",),
    "H330": ("GHS06",),
    "H331": ("GHS06",),
    "H332": ("GHS07",),
    "H334": ("GHS08",),
    "H335": ("GHS07",),
    "H336": ("GHS07",),
    "H340": ("GHS08",),
    "H341": ("GHS08",),
    "H350": ("GHS08",),
    "H351": ("GHS08",),
    "H360": ("GHS08",),
    "H361": ("GHS08",),
    "H370": ("GHS08",),
    "H371": ("GHS08",),
    "H372": ("GHS08",),
    "H373": ("GHS08",),
    "H400": ("GHS09",),
    "H410": ("GHS09",),
    "H411": ("GHS09",),
    "H420": ("GHS07",),
    "H421": ("GHS07",),
}


def pictograms_for(code: str) -> tuple[str, ...]:
    """GHS pictogram codes for a (possibly combined) hazard statement."""
    seen: list[str] = []
    for part in code.split("+"):
        for pictogram in PICTOGRAMS_FOR.get(part, ()):
            if pictogram not in seen:
                seen.append(pictogram)
    return tuple(seen)
