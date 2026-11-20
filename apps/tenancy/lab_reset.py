"""Bulk deletion of a lab's inventory or requests, e.g. before a fresh LabSuit import.

Both operations are scoped to one lab, run in a single transaction, and leave one audit
entry with the counts. The audit log itself is never touched (it is append-only), so the
history of what was deleted stays on record. Stored files (attachments, purchase-order
PDFs) are removed by their models' ``post_delete`` hooks once the transaction commits.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.audit.models import AuditEntry
from apps.inventory.models import Item, Location, Tag
from apps.procurement.models import Request

from .models import Lab, User


@dataclass(frozen=True)
class InventoryCounts:
    items: int
    locations: int
    tags: int


@dataclass(frozen=True)
class RequestCounts:
    requests: int


def _unused_tags(lab: Lab):
    # Tags are shared with requests; keep the ones requests still carry so deleting the
    # inventory doesn't strip labels off the order history.
    return Tag.objects.filter(lab=lab, requests__isnull=True)


def inventory_counts(lab: Lab) -> InventoryCounts:
    """What :func:`delete_inventory` would remove right now."""
    return InventoryCounts(
        items=Item.objects.filter(lab=lab).count(),
        locations=Location.objects.filter(lab=lab).count(),
        tags=_unused_tags(lab).distinct().count(),
    )


def request_counts(lab: Lab) -> RequestCounts:
    """What :func:`delete_requests` would remove right now."""
    return RequestCounts(requests=Request.objects.filter(lab=lab).count())


@transaction.atomic
def delete_inventory(lab: Lab, *, actor: User) -> InventoryCounts:
    """Delete all of ``lab``'s items (with their attachments, comments and scan history),
    its locations, and the tags no request uses. Requests that came from or produced an
    item keep existing; they just lose that link. The item-ID counter is left alone so a
    deleted item's ID is never handed out again to a new one.
    """
    counts = inventory_counts(lab)
    Item.objects.filter(lab=lab).delete()
    Location.objects.filter(lab=lab).delete()
    Tag.objects.filter(pk__in=_unused_tags(lab).values("pk")).delete()
    AuditEntry.record(
        lab=lab,
        actor=actor,
        action="lab.inventory_deleted",
        target=lab,
        changes={"items": counts.items, "locations": counts.locations, "tags": counts.tags},
    )
    return counts


@transaction.atomic
def delete_requests(lab: Lab, *, actor: User) -> RequestCounts:
    """Delete all of ``lab``'s requests, including imported order history, with their
    purchase orders, attachments and comments. Suppliers, budgets and shipping addresses
    are kept.
    """
    counts = request_counts(lab)
    Request.objects.filter(lab=lab).delete()
    AuditEntry.record(
        lab=lab,
        actor=actor,
        action="lab.requests_deleted",
        target=lab,
        changes={"requests": counts.requests},
    )
    return counts
