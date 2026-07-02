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
from apps.inventory import ids
from apps.inventory.models import Item
from apps.tenancy.models import User

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
        # Delivery is handled by receive() (a dialog), not a one-click transition, because
        # the receiver chooses between checking the item in and closing it untracked.
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

    req.status = transition.to_status
    req.save()

    AuditEntry.record(
        lab=req.lab,
        actor=actor,
        action=f"procurement.request_{action}",
        target=req,
        changes={"from": previous, "to": req.status},
    )
    _notify_transition(req.pk, previous, req.status)
    return req


def can_receive(user, req: Request) -> bool:
    """Whether ``req`` is awaiting delivery and ``user`` may receive it."""
    return req.status in (Status.ORDERED, Status.DELIVERED) and user.can(req.lab, "check_in")


def purchase_coordinators(lab):
    """Lab members who can place orders — the people a request can be forwarded to."""
    return (
        User.objects.filter(
            memberships__lab=lab,
            memberships__roles__permissions__code="place_order",
        )
        .exclude(email="")
        .distinct()
        .order_by("email")
    )


def can_forward(user, req: Request) -> bool:
    """Whether an approved request may be forwarded to a purchase coordinator by ``user``."""
    if req.status != Status.APPROVED:
        return False
    return (
        req.requested_by_id == user.pk
        or user.can(req.lab, "approve_request")
        or user.can(req.lab, "place_order")
        or user.can(req.lab, "manage_lab")
    )


@transaction.atomic
def forward(req: Request, *, actor, assignee: User) -> Request:
    """Assign an approved request to a purchase coordinator and notify them."""
    req.assigned_to = assignee
    req.save()
    AuditEntry.record(
        lab=req.lab,
        actor=actor,
        action="procurement.request_forwarded",
        target=req,
        changes={"assigned_to": assignee.email},
    )

    def _notify() -> None:
        from apps.notifications.tasks import notify_request_assigned

        transaction.on_commit(lambda: notify_request_assigned.delay(req.pk))

    _notify()
    return req


def can_self_approve(user, req: Request) -> bool:
    """Whether ``user`` may self-approve ``req``.

    Allowed only for the requester's own still-pending request when they hold
    ``self_approve``. Hidden from users who can already ``approve_request`` — they use the
    normal one-click Approve, which already covers their own requests — so no duplicate
    button appears.
    """
    return (
        req.status == Status.REQUESTED
        and req.requested_by_id == user.pk
        and user.can(req.lab, "self_approve")
        and not user.can(req.lab, "approve_request")
    )


@transaction.atomic
def self_approve(req: Request, *, actor, note: str = "") -> Request:
    """Approve one's own request, recording the (typically in-person) authorisation.

    Behaves like a manager approval — sets the approver and moves to Approved — but also
    posts a visible comment so the self-approval stays on the record. Raises
    :class:`TransitionError` if the request is not awaiting approval.
    """
    if req.status != Status.REQUESTED:
        raise TransitionError(
            f"cannot self-approve a request that is {req.get_status_display()!r}"
        )

    previous = req.status
    req.approver = actor
    req.status = Status.APPROVED
    req.save()

    AuditEntry.record(
        lab=req.lab,
        actor=actor,
        action="procurement.request_self_approved",
        target=req,
        changes={"from": previous, "to": req.status},
    )

    # Leave a visible record that this was self-approved (approved in person).
    from apps.comments.models import Comment

    body = "Self-approved — authorised by lab management in person."
    if note:
        body += f"\n\n{note}"
    Comment.objects.create(lab=req.lab, author=actor, target=req, body=body)

    _notify_transition(req.pk, previous, req.status)
    return req


@transaction.atomic
def receive(
    req: Request, *, actor, create_item: bool, location=None, human_id: str = ""
) -> Request:
    """Receive a delivered order.

    Two outcomes: ``create_item=True`` checks it into inventory (creates the item at the
    given location, with the chosen ``human_id`` or the next free ID, and moves the
    request to Checked in); ``create_item=False`` records delivery of something we don't
    track (software, services) and moves it to Delivered. Raises :class:`TransitionError`
    if the request is not awaiting delivery.
    """
    if req.status not in (Status.ORDERED, Status.DELIVERED):
        raise TransitionError(f"cannot receive a request that is {req.get_status_display()!r}")

    previous = req.status
    if create_item:
        _create_item_from(req, location=location, human_id=human_id)
        req.status = Status.CHECKED_IN
        action = "checked_in"
        changes = {"from": previous, "to": req.status, "item": req.created_item.human_id}
    else:
        req.status = Status.DELIVERED
        action = "delivered_untracked"
        changes = {"from": previous, "to": req.status}
    req.save()

    AuditEntry.record(
        lab=req.lab,
        actor=actor,
        action=f"procurement.request_{action}",
        target=req,
        changes=changes,
    )
    _notify_transition(req.pk, previous, req.status)
    return req


def _notify_transition(req_pk: int, previous: str, new: str) -> None:
    """Enqueue the status-change email once the surrounding transaction commits."""
    # Imported lazily so procurement doesn't import the notifications app at load time.
    from apps.notifications.tasks import notify_request_transition

    transaction.on_commit(lambda: notify_request_transition.delay(req_pk, previous, new))


def _create_item_from(req: Request, *, location=None, human_id: str = "") -> Item:
    """Create the inventory item a checked-in request delivers and link it back."""
    item = Item.objects.create(
        lab=req.lab,
        human_id=human_id or ids.suggest_ids(req.lab, 1)[0],
        name=req.item_name,
        location=location,
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
