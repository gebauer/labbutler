"""What a newcomer should see: the role-aware welcome tour and the getting-started list.

Both are derived, never stored: tour steps follow the permissions a member holds, and
each checklist item ticks itself off from real data (a display name is set, the lab has
locations, …). The only stored bit is the per-lab "dismissed" stamp on the membership.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.urls import reverse

from .catalog import ALL_PERMISSION_CODES
from .models import Lab, Membership, Permission, User

# Tour steps in display order, each shown when the member holds the gating permission
# (None = everyone). The step text lives in tenancy/onboarding.html, keyed by name.
_TOUR = [
    ("profile", None),
    ("find", "view_inventory"),
    ("scan", "view_inventory"),
    ("request", "create_request"),
    ("approve", "approve_request"),
    ("order", "place_order"),
    ("receive", "check_in"),
    ("sign", "sign_po"),
    ("setup", "manage_lab"),
    ("rights", None),
]


def permission_codes(user: User, lab: Lab | None) -> set[str]:
    """Every permission ``user`` holds in ``lab``, in one query."""
    if lab is None:
        return set()
    if user.is_superuser:
        return set(ALL_PERMISSION_CODES)
    return set(
        Permission.objects.filter(
            roles__memberships__user=user, roles__memberships__lab=lab
        ).values_list("code", flat=True)
    )


def tour_steps(user: User, lab: Lab | None) -> list[str]:
    """Keys of the welcome-tour steps relevant to ``user`` in ``lab``, in order."""
    codes = permission_codes(user, lab)
    return [key for key, needs in _TOUR if needs is None or needs in codes]


@dataclass(frozen=True)
class ChecklistItem:
    label: str
    done: bool
    url: str
    hint: str = ""


def checklist(user: User, lab: Lab) -> list[ChecklistItem]:
    """Getting-started steps for ``user`` in ``lab``: personal ones, plus lab setup for
    managers. Each item is ticked from the data, so it can't drift from reality."""
    from apps.inventory.models import Item, Location
    from apps.procurement.models import Budget, Request, ShippingAddress, Vendor

    codes = permission_codes(user, lab)
    items = [
        ChecklistItem(
            "Set your display name",
            bool(user.friendly_name),
            reverse("tenancy:settings"),
            "So colleagues see your name instead of your email.",
        ),
        ChecklistItem(
            "Read the welcome tour",
            user.onboarding_seen_at is not None,
            reverse("tenancy:onboarding"),
        ),
    ]
    if "create_request" in codes:
        items.append(
            ChecklistItem(
                "Raise your first request",
                Request.objects.filter(lab=lab, requested_by=user).exists(),
                reverse("procurement:request_create"),
            )
        )
    if "manage_lab" in codes:
        manage = "manage:list"
        items += [
            ChecklistItem(
                "Add storage locations",
                Location.objects.filter(lab=lab).exists(),
                reverse(manage, args=["locations"]),
                "Rooms, fridges, cabinets — items are filed under them.",
            ),
            ChecklistItem(
                "Add suppliers",
                Vendor.objects.filter(lab=lab).exists(),
                reverse(manage, args=["suppliers"]),
            ),
            ChecklistItem(
                "Add budgets (Kostenstellen)",
                Budget.objects.filter(lab=lab).exists(),
                reverse(manage, args=["budgets"]),
            ),
            ChecklistItem(
                "Add a shipping address",
                ShippingAddress.objects.filter(lab=lab).exists(),
                reverse(manage, args=["addresses"]),
            ),
            ChecklistItem(
                "Bring in your inventory",
                Item.objects.filter(lab=lab).exists(),
                reverse("imports:start")
                if "import_inventory" in codes
                else reverse("inventory:item_create"),
                "Import a LabSuit export or another spreadsheet, or add items by hand.",
            ),
            ChecklistItem(
                "Invite your team",
                bool(lab.join_token) or Membership.objects.filter(lab=lab).count() > 1,
                reverse("manage:members") + "#join-link",
                "Add people by email, or share a join link.",
            ),
        ]
    return items


def checklist_for_dashboard(user: User, lab: Lab) -> list[ChecklistItem]:
    """The checklist to show on the dashboard, or [] once done or dismissed."""
    membership = Membership.objects.filter(user=user, lab=lab).first()
    if membership is None or membership.checklist_dismissed_at is not None:
        return []
    items = checklist(user, lab)
    return items if not all(item.done for item in items) else []
