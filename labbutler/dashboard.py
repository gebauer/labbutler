"""Role-aware home dashboard: the actionable widgets a user sees for their lab.

Each widget is gated on a permission and carries a small, ordered slice of the work
waiting for the user, plus a link to the full filtered list. Rendering (including the
inline action buttons) lives in ``dashboard.html``; this module only decides *what* to
show and is pure aside from the queries it runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

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

    def add(key, title, kind, queryset, view_all, empty):
        widgets.append(
            Widget(key, title, kind, list(queryset[:_LIMIT]), queryset.count(), view_all, empty)
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

    assigned = requests.filter(assigned_to=user, status=Status.APPROVED).order_by("created_at")
    if user.can(lab, "place_order") or assigned.exists():
        add(
            "to_order",
            "Forwarded to you to order",
            "to_order",
            assigned,
            f"{list_url}?assignee={user.pk}&status=approved",
            "Nothing forwarded to you.",
        )

    if user.can(lab, "check_in"):
        qs = requests.filter(status__in=[Status.ORDERED, Status.DELIVERED]).order_by(
            "expected_delivery", "created_at"
        )
        add(
            "deliveries",
            "Expecting deliveries",
            "deliveries",
            qs,
            f"{list_url}?status=ordered&status=delivered",
            "No deliveries expected.",
        )

    if user.can(lab, "create_request"):
        open_states = [Status.REQUESTED, Status.APPROVED, Status.ORDERED, Status.DELIVERED]
        qs = requests.filter(requested_by=user, status__in=open_states).order_by("-created_at")
        add(
            "my_requests",
            "My open requests",
            "my_requests",
            qs,
            f"{list_url}?requester={user.pk}",
            "You have no open requests.",
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
