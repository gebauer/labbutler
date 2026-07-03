"""Role-aware home dashboard: the actionable widgets a user sees for their lab.

Each widget is gated on a permission and carries a small, ordered slice of the work
waiting for the user, plus a link to the full filtered list. Rendering (including the
inline action buttons) lives in ``dashboard.html``; this module only decides *what* to
show and is pure aside from the queries it runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.inventory.models import Item
from apps.procurement.models import Request

Status = Request.Status
_LIMIT = 6  # items shown per widget before "View all"


@dataclass
class Widget:
    key: str
    title: str
    kind: str  # drives which action buttons the template renders
    items: list
    total: int
    view_all_url: str
    empty: str


def build(user, lab) -> list[Widget]:
    """The widgets ``user`` should see for ``lab``, in a sensible default order."""
    widgets: list[Widget] = []
    requests = Request.objects.filter(lab=lab).select_related(
        "vendor", "requested_by", "assigned_to"
    )
    list_url = reverse("procurement:request_list")

    def add(key, title, kind, queryset, view_all, empty, limit=_LIMIT):
        widgets.append(
            Widget(key, title, kind, list(queryset[:limit]), queryset.count(), view_all, empty)
        )

    if user.can(lab, "approve_request"):
        qs = requests.filter(status=Status.REQUESTED).order_by("created_at")
        add(
            "approvals",
            "Requests to approve",
            "approvals",
            qs,
            f"{list_url}?status=requested",
            "Nothing waiting for approval.",
        )

    if user.can(lab, "place_order"):
        # Approved requests this user could place: unassigned ones plus those forwarded
        # to them — but not work already forwarded to somebody else. Gated on the
        # permission (not the Purchase coordinator role name) so anyone who may order
        # can actually do so from here (#10).
        qs = (
            requests.filter(status=Status.APPROVED)
            .filter(Q(assigned_to__isnull=True) | Q(assigned_to=user))
            .order_by("created_at")
        )
        add(
            "to_order",
            "Requests to order",
            "to_order",
            qs,
            f"{list_url}?status=approved",
            "Nothing waiting to be ordered.",
        )

    if user.can(lab, "check_in"):
        # Only deliveries the viewer is involved in: raised by them or forwarded to them
        # to order — not every open delivery in the lab.
        qs = (
            requests.filter(status__in=[Status.ORDERED, Status.DELIVERED])
            .filter(Q(requested_by=user) | Q(assigned_to=user))
            .order_by("expected_delivery", "created_at")
        )
        add(
            "deliveries",
            "Expecting deliveries",
            "deliveries",
            qs,
            f"{list_url}?mine=1&status=ordered&status=delivered",
            "No deliveries expected.",
            limit=10,
        )

    if user.can(lab, "create_request"):
        # Mine that still need a push: awaiting approval, or approved but not yet
        # forwarded to a coordinator or ordered.
        qs = (
            requests.filter(requested_by=user)
            .filter(
                Q(status=Status.REQUESTED) | Q(status=Status.APPROVED, assigned_to__isnull=True)
            )
            .order_by("-created_at")
        )
        add(
            "my_requests",
            "My pending requests",
            "my_requests",
            qs,
            f"{list_url}?requester={user.pk}&status=requested&status=approved",
            "You have no pending requests.",
        )

        # Mine that are being handled by someone else — follow, but nothing to do.
        tracking = (
            requests.filter(requested_by=user)
            .filter(
                Q(status=Status.ORDERED)
                | Q(status=Status.DELIVERED)
                | Q(status=Status.APPROVED, assigned_to__isnull=False)
            )
            .order_by("-created_at")
        )
        add(
            "tracking",
            "My requests in progress",
            "tracking",
            tracking,
            f"{list_url}?requester={user.pk}&status=approved&status=ordered&status=delivered",
            "Nothing of yours is in progress.",
        )

    if user.can(lab, "manage_inventory"):
        horizon = timezone.localdate() + timedelta(days=30)
        items = (
            Item.objects.filter(
                lab=lab, expiration_date__isnull=False, expiration_date__lte=horizon
            )
            .select_related("location")
            .order_by("expiration_date")
        )
        if items.exists():
            add(
                "expiring",
                "Expiring soon",
                "expiring",
                items,
                reverse("inventory:item_list"),
                "Nothing expiring soon.",
            )

    return widgets
