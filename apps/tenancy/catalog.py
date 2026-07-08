"""Fixed, installation-wide permission catalog and the starter template roles.

These are the single source of truth seeded by a data migration. The permission set is
global and closed; roles are per-lab and cloned from the templates at lab creation.
"""

# (code, human label) — the MVP permission catalog from the spec.
PERMISSION_CATALOG: list[tuple[str, str]] = [
    ("view_inventory", "See inventory"),
    ("view_requests", "See requests"),
    ("manage_inventory", "Create/edit/delete items, fields, presets, locations, tags"),
    ("import_inventory", "Run spreadsheet imports"),
    ("create_request", "Raise a request"),
    ("approve_request", "Approve a request"),
    ("self_approve", "Approve your own requests (with confirmation)"),
    ("place_order", "Mark an approved request as ordered"),
    ("accept_forwards", "Receive forwarded requests (appear in the forward-to list)"),
    ("create_po", "Upload the central-purchasing order form (Beschaffungsantrag)"),
    ("sign_po", "Sign purchase orders (asked to sign and upload the signed form)"),
    ("send_po_to_central", "Mark a signed purchase order as sent to central purchasing"),
    ("reroute_procurement", "Change a request's procurement route after approval"),
    ("check_in", "Receive/check items into inventory"),
    ("check_out", "Consume/remove items from inventory"),
    ("manage_lab", "Members, roles, suppliers, budgets, shipping addresses, settings"),
]

ALL_PERMISSION_CODES = [code for code, _ in PERMISSION_CATALOG]

# Starter roles cloned into editable, lab-owned roles when a lab is created.
# name -> list of permission codes ("*" means every permission).
TEMPLATE_ROLES: dict[str, list[str]] = {
    "Lab manager": ["*"],
    "Member": [
        "view_inventory",
        "view_requests",
        "manage_inventory",
        "create_request",
        "self_approve",
        "check_in",
        "check_out",
    ],
    "Viewer": ["view_inventory", "view_requests"],
    # Order-responsible staff: approved requests are forwarded to them to place.
    "Purchase coordinator": [
        "view_requests",
        "place_order",
        "accept_forwards",
        "create_po",
        "send_po_to_central",
        "reroute_procurement",
    ],
}
