"""Procurement request workflow: the status state machine and its side effects.

The allowed moves and the permission each requires live in one table (:data:`TRANSITIONS`)
so views and templates ask *this* module what a user may do next rather than hard-coding
status logic. Transitions are applied inside a transaction; checking a request in creates
the inventory item and links it back.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.audit.models import AuditEntry
from apps.inventory.models import Item

from .models import Request

Status = Request.Status


@dataclass(frozen=True)
class Transition:
    action: str
    label: str
    to_status: str
    from_statuses: frozenset[str]
    permission: str
    danger: bool = False  # a rejecting/cancelling move, styled as destructive


TRANSITIONS: dict[str, Transition] = {
    t.action: t
    for t in [
        Transition(
            "approve", "Approve", Status.APPROVED, frozenset({Status.REQUESTED}), "approve_request"
        ),
        Transition(
            "reject",
            "Reject",
            Status.REJECTED,
            frozenset({Status.REQUESTED}),
            "approve_request",
            danger=True,
        ),
        Transition(
            "order", "Mark ordered", Status.ORDERED, frozenset({Status.APPROVED}), "place_order"
        ),
        Transition(
            "deliver",
            "Mark delivered",
            Status.DELIVERED,
            frozenset({Status.ORDERED}),
            "place_order",
        ),
        Transition(
            "check_in",
            "Check in → create item",
            Status.CHECKED_IN,
            frozenset({Status.ORDERED, Status.DELIVERED}),
            "check_in",
        ),
        Transition(
            "cancel",
            "Cancel",
            Status.CANCELLED,
            frozenset({Status.REQUESTED, Status.APPROVED, Status.ORDERED, Status.DELIVERED}),
            "create_request",  # plus an ownership check, see may_perform
            danger=True,
        ),
    ]
}


class TransitionError(ValueError):
    """Raised when a workflow move is not valid from the request's current status."""


def may_perform(user, req: Request, transition: Transition) -> bool:
    """Whether ``user`` may apply ``transition`` to ``req`` right now."""
    if req.status not in transition.from_statuses:
        return False
    if transition.action == "cancel":
        # The requester can always cancel their own; otherwise a lab manager may.
        return req.requested_by_id == user.pk or user.can(req.lab, "manage_lab")
    return user.can(req.lab, transition.permission)


def available_transitions(user, req: Request) -> list[Transition]:
    """The workflow moves ``user`` may make on ``req`` now (for rendering buttons)."""
    return [t for t in TRANSITIONS.values() if may_perform(user, req, t)]


@transaction.atomic
def perform_transition(req: Request, action: str, *, actor, po_number: str = "") -> Request:
    """Apply ``action`` to ``req``, running its side effects, and write an audit entry.

    Raises :class:`TransitionError` if the move is not allowed from the current status;
    permission is the caller's responsibility (see :func:`may_perform`).
    """
    transition = TRANSITIONS.get(action)
    if transition is None:
        raise TransitionError(f"unknown action: {action!r}")
    if req.status not in transition.from_statuses:
        raise TransitionError(f"cannot {action} a request that is {req.get_status_display()!r}")

    previous = req.status
    if transition.action == "approve":
        req.approver = actor
    elif transition.action == "order" and po_number:
        req.po_number = po_number
    elif transition.action == "check_in":
        _create_item_from(req)

    req.status = transition.to_status
    req.save()

    AuditEntry.record(
        lab=req.lab,
        actor=actor,
        action=f"procurement.request_{action}",
        target=req,
        changes={"from": previous, "to": req.status},
    )
    return req


def _create_item_from(req: Request) -> Item:
    """Create the inventory item a checked-in request delivers and link it back."""
    item = Item.objects.create(
        lab=req.lab,
        human_id=req.lab.allocate_item_id(),
        name=req.item_name,
        catalog_number=req.catalog_number,
        cas_number=req.cas_number,
        vendor=req.vendor,
        owner=req.requested_by,
        price_amount=req.unit_price,
        price_currency=req.currency,
    )
    item.tags.set(req.tags.all())
    req.created_item = item
    return item
