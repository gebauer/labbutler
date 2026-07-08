"""Procurement request workflow: the status state machine and its side effects.

The allowed moves and the permission each requires live in one table (:data:`TRANSITIONS`)
so views and templates ask *this* module what a user may do next rather than hard-coding
status logic. Transitions are applied inside a transaction; checking a request in creates
the inventory item and links it back.

Also home to vendor maintenance: duplicate detection and merging, so lab managers can
sanitize supplier names that were typed in different spellings.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count
from django.urls import reverse

from apps.attachments.models import Attachment
from apps.audit.models import AuditEntry
from apps.inventory import ids
from apps.inventory.models import Item
from apps.tenancy.models import User

from . import suggestions
from .models import PurchaseOrder, Request, Vendor, normalize_vendor_name

Status = Request.Status
Route = Request.Route

# While the route may still change, nothing has left the organization. From PO_Sent
# onward the route is locked: undoing an external commitment is a cancellation
# (deferred), not a re-route.
ROUTE_MUTABLE_STATUSES = frozenset({Status.APPROVED, Status.PO_CREATED, Status.PO_SIGNED})

# Reason codes offered (all optional) when a user keeps DIRECT against a CENTRAL
# suggestion. The override *event* is mandatory; the reason never is — an emergency at
# 23:00 costs one click, not a form, and an empty reason is itself a signal.
OVERRIDE_REASONS: dict[str, str] = {
    "emergency": "Emergency — needed immediately",
    "known_below_threshold": "Final price is known to be below the threshold",
    "vendor_exception": "Vendor exception (e.g. existing framework agreement)",
}


def _direct_route_or_po_sent(req: Request) -> bool:
    # "Mark ordered" is one action with two doors: straight from Approved on the direct
    # route, or after central purchasing confirmed (from PO sent) on the central route.
    return req.status != Status.APPROVED or req.procurement_route == Route.DIRECT


@dataclass(frozen=True)
class Transition:
    action: str
    label: str
    to_status: str
    from_statuses: frozenset[str]
    permission: str
    danger: bool = False  # a rejecting/cancelling move, styled as destructive
    # Extra state-dependent condition beyond from_statuses (e.g. the request's route).
    guard: Callable[[Request], bool] | None = None


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
            "order",
            "Mark ordered",
            Status.ORDERED,
            frozenset({Status.APPROVED, Status.PO_SENT}),
            "place_order",
            guard=_direct_route_or_po_sent,
        ),
        Transition(
            "send_to_zk",
            "Sent to central purchasing",
            Status.PO_SENT,
            frozenset({Status.PO_SIGNED}),
            "send_po_to_central",  # or the request's manager, see may_perform
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


def request_manager(req: Request) -> User | None:
    """The person managing this particular request: the assignee if it was forwarded,
    else the original requester. PO handoffs address this specific person, never a role."""
    return req.assigned_to or req.requested_by


def may_perform(user, req: Request, transition: Transition) -> bool:
    """Whether ``user`` may apply ``transition`` to ``req`` right now."""
    if req.status not in transition.from_statuses:
        return False
    if transition.guard is not None and not transition.guard(req):
        return False
    if transition.action == "cancel":
        # The requester can always cancel their own; otherwise a lab manager may.
        return req.requested_by_id == user.pk or user.can(req.lab, "manage_lab")
    if transition.action == "send_to_zk":
        # The request's manager forwards the ready-made email themselves, so they may
        # record the fact even without the lab-wide permission.
        manager = request_manager(req)
        if manager is not None and manager.pk == user.pk:
            return True
    return user.can(req.lab, transition.permission)


def available_transitions(user, req: Request) -> list[Transition]:
    """The workflow moves ``user`` may make on ``req`` now (for rendering buttons)."""
    return [t for t in TRANSITIONS.values() if may_perform(user, req, t)]


@transaction.atomic
def perform_transition(
    req: Request,
    action: str,
    *,
    actor,
    po_number: str = "",
    zk_order_number: str = "",
    override_reason_code: str = "",
    override_reason_text: str = "",
) -> Request:
    """Apply ``action`` to ``req``, running its side effects, and write an audit entry.

    Raises :class:`TransitionError` if the move is not allowed from the current status;
    permission is the caller's responsibility (see :func:`may_perform`).
    """
    transition = TRANSITIONS.get(action)
    if transition is None:
        raise TransitionError(f"unknown action: {action!r}")
    if req.status not in transition.from_statuses or (
        transition.guard is not None and not transition.guard(req)
    ):
        raise TransitionError(f"cannot {action} a request that is {req.get_status_display()!r}")

    previous = req.status
    changes: dict = {"from": previous, "to": transition.to_status}
    if transition.action == "approve":
        req.approver = actor
    elif transition.action == "order":
        if po_number:
            req.po_number = po_number
        if previous == Status.PO_SENT and zk_order_number:
            req.zk_order_number = zk_order_number
            changes["zk_order_number"] = zk_order_number
        # Proceeding DIRECT although the engine suggests CENTRAL is the one intentional
        # friction point: the event is mandatory (and non-blocking), the reason is not.
        if previous == Status.APPROVED and req.procurement_route == Route.DIRECT:
            suggestion = suggestions.suggest_route(req)
            if suggestion.route == Route.CENTRAL:
                record_route_override(
                    req,
                    actor=actor,
                    suggestion=suggestion,
                    reason_code=override_reason_code,
                    reason_text=override_reason_text,
                )

    req.status = transition.to_status
    req.save()

    AuditEntry.record(
        lab=req.lab,
        actor=actor,
        action=f"procurement.request_{action}",
        target=req,
        changes=changes,
    )
    # Auto-forward chosen at request time: on approval the picked coordinator takes
    # over. Runs in the same transaction, so the status email (sent after commit)
    # already reports the request as forwarded.
    if transition.action == "approve" and req.forward_to_id and not req.assigned_to_id:
        forward(req, actor=actor, assignee=req.forward_to)
    _notify_transition(req.pk, previous, req.status)
    return req


def can_receive(user, req: Request) -> bool:
    """Whether ``req`` is awaiting delivery and ``user`` may receive it."""
    return req.status in (Status.ORDERED, Status.DELIVERED) and user.can(req.lab, "check_in")


def forward_recipients(lab):
    """Lab members a request can be forwarded to: holders of ``accept_forwards``.

    Deliberately its own permission rather than ``place_order`` — in labs where
    everyone may order but only a few (e.g. the technicians) handle forwarded
    requests, the forward-to list stays short.
    """
    return (
        User.objects.filter(
            memberships__lab=lab,
            memberships__roles__permissions__code="accept_forwards",
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

        transaction.on_commit(lambda: notify_request_assigned.delay(req.pk, actor.pk))

    _notify()
    return req


# --- Central purchasing (Zentraleinkauf) ---------------------------------------------


def signer_recipients(lab):
    """Lab members asked to sign purchase orders: holders of ``sign_po``."""
    return (
        User.objects.filter(
            memberships__lab=lab,
            memberships__roles__permissions__code="sign_po",
        )
        .exclude(email="")
        .distinct()
        .order_by("email")
    )


def can_create_po(user, req: Request) -> bool:
    """Whether ``user`` may upload the (new or replacement) official order form.

    Open to ``create_po`` holders and always to the request's manager — the person the
    upload is prompted from, who may hold no lab-wide role at all.
    """
    if req.procurement_route != Route.CENTRAL or req.status not in ROUTE_MUTABLE_STATUSES:
        return False
    manager = request_manager(req)
    if manager is not None and manager.pk == user.pk:
        return True
    return user.can(req.lab, "create_po")


@transaction.atomic
def create_po(req: Request, *, actor, upload) -> PurchaseOrder:
    """Attach the filled official order form, freezing the net snapshot.

    From ``Approved`` this opens the central branch; from ``PO created``/``PO signed``
    it replaces the current form (wrong file, price drift): the old PO is archived as
    superseded and the state returns to ``PO created`` — signatures on a superseded PO
    are moot, so recreation implies re-signing. v1 stores the PDF without inspecting it.
    """
    if req.procurement_route != Route.CENTRAL:
        raise TransitionError("a purchase order only exists on the central-purchasing route")
    if req.status not in ROUTE_MUTABLE_STATUSES:
        raise TransitionError(
            f"cannot attach an order form to a request that is {req.get_status_display()!r}"
        )

    previous = req.status
    superseded = _supersede_active_po(req, actor=actor, cause="recreated")
    po = PurchaseOrder.objects.create(
        request=req,
        po_snapshot_net=req.net_total,
        unsigned_pdf=upload,
        created_by=actor,
    )
    req.status = Status.PO_CREATED
    req.save()

    changes = {
        "from": previous,
        "to": req.status,
        "po": po.pk,
        "snapshot_net": str(po.po_snapshot_net),
        "source": "uploaded",
    }
    if superseded is not None:
        changes["superseded_po"] = superseded.pk
    AuditEntry.record(
        lab=req.lab, actor=actor, action="procurement.po_created", target=req, changes=changes
    )

    from apps.notifications.tasks import notify_po_signature_needed

    transaction.on_commit(lambda: notify_po_signature_needed.delay(req.pk))
    if previous != req.status:
        _notify_transition(req.pk, previous, req.status)
    return po


def can_upload_signed_po(user, req: Request) -> bool:
    """Whether ``user`` may upload the signed order form (the ``sign_po`` holders)."""
    return req.status == Status.PO_CREATED and user.can(req.lab, "sign_po")


@transaction.atomic
def upload_signed_po(req: Request, *, actor, upload) -> PurchaseOrder:
    """Store the signed form on the active PO and move to ``PO signed``.

    Trust-based in v1 — no signature verification; the audit entry records who uploaded.
    Enqueues the forward-ready ZK email to the request's manager on commit.
    """
    if req.status != Status.PO_CREATED:
        raise TransitionError(
            f"cannot upload a signed form for a request that is {req.get_status_display()!r}"
        )
    po = req.active_purchase_order()
    if po is None:
        raise TransitionError("no active purchase order to sign")

    po.signed_pdf = upload
    po.signed_uploaded_by = actor
    po.save()
    previous = req.status
    req.status = Status.PO_SIGNED
    req.save()

    AuditEntry.record(
        lab=req.lab,
        actor=actor,
        action="procurement.po_signed",
        target=req,
        changes={"from": previous, "to": req.status, "po": po.pk, "uploaded_by": actor.email},
    )

    from apps.notifications.tasks import send_zk_forward_email

    transaction.on_commit(lambda: send_zk_forward_email.delay(req.pk))
    _notify_transition(req.pk, previous, req.status)
    return po


def can_resend_zk_email(user, req: Request) -> bool:
    """Whether ``user`` may re-send the forward-ready ZK email (lost mail, reassignment)."""
    if req.status not in (Status.PO_SIGNED, Status.PO_SENT):
        return False
    manager = request_manager(req)
    if manager is not None and manager.pk == user.pk:
        return True
    return user.can(req.lab, "send_po_to_central") or user.can(req.lab, "manage_lab")


def can_reroute(user, req: Request) -> bool:
    """Whether ``user`` may change the procurement route (mutable zone only)."""
    return req.status in ROUTE_MUTABLE_STATUSES and user.can(req.lab, "reroute_procurement")


@transaction.atomic
def reroute(
    req: Request, *, actor, to_route: str, reason_code: str = "", reason_text: str = ""
) -> Request:
    """Manually switch the procurement route; canonical reset back to ``Approved``.

    Allowed only while nothing has left the organization (``Approved``/``PO created``/
    ``PO signed``). Leaving the central route archives the existing PO as superseded —
    it is moot on the direct path. From ``PO sent`` onward this raises: beyond the lock
    a route change is a cancellation, which is a separate (deferred) workflow.
    """
    if req.status not in ROUTE_MUTABLE_STATUSES:
        raise TransitionError(
            f"the route is locked once the PO left the organization ({req.get_status_display()})"
        )
    if to_route not in Route.values:
        raise TransitionError(f"unknown route: {to_route!r}")
    if to_route == req.procurement_route:
        raise TransitionError("the request already is on that route")

    from_route = req.procurement_route
    previous_status = req.status
    superseded = None
    if from_route == Route.CENTRAL:
        superseded = _supersede_active_po(req, actor=actor, cause="rerouted")

    req.procurement_route = to_route
    req.status = Status.APPROVED
    req.save()

    changes = {
        "from_route": from_route,
        "to_route": to_route,
        "from_status": previous_status,
        "to_status": req.status,
    }
    if reason_code in OVERRIDE_REASONS:
        changes["reason_code"] = reason_code
    if reason_text:
        changes["reason_text"] = reason_text
    if superseded is not None:
        changes["superseded_po"] = superseded.pk
    AuditEntry.record(
        lab=req.lab, actor=actor, action="procurement.route_changed", target=req, changes=changes
    )

    # Choosing DIRECT against a CENTRAL suggestion is recorded — always, unsuppressibly.
    if to_route == Route.DIRECT:
        suggestion = suggestions.suggest_route(req)
        if suggestion.route == Route.CENTRAL:
            record_route_override(
                req,
                actor=actor,
                suggestion=suggestion,
                reason_code=reason_code,
                reason_text=reason_text,
            )

    if previous_status != req.status:
        _notify_transition(req.pk, previous_status, req.status)
    return req


def record_route_override(
    req: Request,
    *,
    actor,
    suggestion: suggestions.RouteSuggestion | None = None,
    reason_code: str = "",
    reason_text: str = "",
) -> None:
    """Write the mandatory ``route_suggestion_overridden`` event (reason optional).

    Carries the decisive context (net, vendor, what was suggested and why) so the
    queries "overrides with no reason" and "override frequency" work regardless of
    whether the reason fields were filled.
    """
    if suggestion is None:
        suggestion = suggestions.suggest_route(req)
    changes = {
        "suggested_route": suggestion.route,
        "suggestion_reasons": list(suggestion.reasons),
        "chosen_route": req.procurement_route,
        "net_total": str(req.net_total),
        "vendor": req.vendor.name if req.vendor_id else "",
        "vendor_country": (req.vendor.country if req.vendor_id else "") or "",
        "reason_code": reason_code if reason_code in OVERRIDE_REASONS else "",
        "reason_text": reason_text,
    }
    AuditEntry.record(
        lab=req.lab,
        actor=actor,
        action="procurement.route_suggestion_overridden",
        target=req,
        changes=changes,
    )


def _supersede_active_po(req: Request, *, actor, cause: str) -> PurchaseOrder | None:
    """Archive the request's active PO (if any) and audit why (recreated/rerouted)."""
    po = req.active_purchase_order()
    if po is None:
        return None
    po.status = PurchaseOrder.Status.SUPERSEDED
    po.save(update_fields=["status", "updated_at"])
    AuditEntry.record(
        lab=req.lab,
        actor=actor,
        action="procurement.po_superseded",
        target=req,
        changes={"po": po.pk, "cause": cause},
    )
    return po


def can_self_approve(user, req: Request) -> bool:
    """Whether ``user`` may self-approve ``req``.

    Allowed only for the requester's own still-pending request when they hold
    ``self_approve``. Offered even to users who also hold ``approve_request``: unlike the
    plain Approve, self-approval leaves an audit entry and a visible comment, so holders
    of both permissions get both actions and choose which record to leave.
    """
    return (
        req.status == Status.REQUESTED
        and req.requested_by_id == user.pk
        and user.can(req.lab, "self_approve")
    )


@transaction.atomic
def self_approve(req: Request, *, actor, note: str = "") -> Request:
    """Approve one's own request, recording the (typically in-person) authorisation.

    Behaves like a manager approval — sets the approver and moves to Approved — but also
    posts a visible comment so the self-approval stays on the record. Raises
    :class:`TransitionError` if the request is not awaiting approval.
    """
    if req.status != Status.REQUESTED:
        raise TransitionError(f"cannot self-approve a request that is {req.get_status_display()!r}")

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
    req: Request,
    *,
    actor,
    create_item: bool,
    location=None,
    human_id: str = "",
    carry_attachments: bool = False,
) -> Request:
    """Receive a delivered order.

    Two outcomes: ``create_item=True`` checks it into inventory (creates the item at the
    given location, with the chosen ``human_id`` or the next free ID, and moves the
    request to Checked in); ``create_item=False`` records receipt of something we don't
    track (software, services) and moves it to Received. Both outcomes are terminal —
    the request cannot be received again. Raises :class:`TransitionError` if the request
    is not awaiting delivery.

    ``carry_attachments`` copies the request's attachments onto the new item. Off by
    default: POs and invoices usually don't belong on the inventory item, only things
    like an SDS or manual do.
    """
    if req.status not in (Status.ORDERED, Status.DELIVERED):
        raise TransitionError(f"cannot receive a request that is {req.get_status_display()!r}")

    previous = req.status
    if create_item:
        _create_item_from(req, location=location, human_id=human_id)
        if carry_attachments:
            for attachment in Attachment.for_object(req):
                attachment.copy_to(req.created_item)

        # Cross-link the item back to its request in the item's comment thread
        # (the request already links forward via ``created_item``).
        from apps.comments.models import Comment

        url = reverse("procurement:request_detail", args=[req.pk])
        Comment.objects.create(
            lab=req.lab,
            author=actor,
            target=req.created_item,
            body=f"Checked in from [Request #{req.pk}]({url}).",
        )

        req.status = Status.CHECKED_IN
        action = "checked_in"
        changes = {"from": previous, "to": req.status, "item": req.created_item.human_id}
    else:
        req.status = Status.RECEIVED
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
        product_url=req.product_url,
        vendor=req.vendor,
        owner=req.requested_by,
        price_amount=req.unit_price,
        price_currency=req.currency,
        signal_word=req.signal_word,
        storage_class=req.storage_class,
    )
    item.tags.set(req.tags.all())
    item.hazards.set(req.hazards.all())
    req.created_item = item
    return item


# --- Vendor maintenance -------------------------------------------------------------

# Two normalized names at or above this SequenceMatcher ratio are suggested as duplicates.
# Advisory only — the manager always confirms the merge — so false positives are cheap.
VENDOR_SIMILARITY_THRESHOLD = 0.85


def _vendor_key(name: str) -> str:
    return normalize_vendor_name(name).casefold()


def find_duplicate_vendors(lab) -> list[list[Vendor]]:
    """Groups of a lab's vendors that look like spellings of the same supplier.

    Vendors are grouped when their normalized names match exactly (case/whitespace
    variants) or are similar per :mod:`difflib`. Pairwise comparison is fine here:
    labs hold at most a few hundred vendors. Returns only groups of two or more,
    each sorted by name.
    """
    vendors = list(Vendor.objects.filter(lab=lab).order_by("name"))
    parent = {v.pk: v.pk for v in vendors}

    def find(pk: int) -> int:
        while parent[pk] != pk:
            parent[pk] = parent[parent[pk]]
            pk = parent[pk]
        return pk

    for i, a in enumerate(vendors):
        key_a = _vendor_key(a.name)
        for b in vendors[i + 1 :]:
            key_b = _vendor_key(b.name)
            if (
                key_a == key_b
                or difflib.SequenceMatcher(None, key_a, key_b).ratio()
                >= VENDOR_SIMILARITY_THRESHOLD
            ):
                parent[find(a.pk)] = find(b.pk)

    groups: dict[int, list[Vendor]] = {}
    for vendor in vendors:
        groups.setdefault(find(vendor.pk), []).append(vendor)
    return sorted(
        (sorted(g, key=lambda v: v.name) for g in groups.values() if len(g) > 1),
        key=lambda g: g[0].name,
    )


@transaction.atomic
def merge_vendors(
    *, lab, winner: Vendor, losers: list[Vendor], actor, new_name: str = ""
) -> Vendor:
    """Merge ``losers`` into ``winner``: repoint their requests and items, delete them.

    Optionally renames the winner in the same step (``new_name``). Everything runs in one
    transaction and is recorded as a single audit entry. Raises :class:`ValueError` on an
    invalid selection (wrong lab, winner among losers, empty losers, or a rename that
    collides with a surviving vendor).
    """
    if not losers:
        raise ValueError("Select at least one vendor to merge into the surviving one.")
    if any(v.lab_id != lab.pk for v in [winner, *losers]):
        raise ValueError("All vendors must belong to the current lab.")
    if any(v.pk == winner.pk for v in losers):
        raise ValueError("The surviving vendor cannot also be merged away.")

    new_name = normalize_vendor_name(new_name)
    renaming = bool(new_name) and new_name != winner.name
    if renaming:
        clash = (
            Vendor.objects.filter(lab=lab, name__iexact=new_name)
            .exclude(pk__in=[v.pk for v in [winner, *losers]])
            .exists()
        )
        if clash:
            raise ValueError(f"A supplier named “{new_name}” already exists.")

    loser_pks = [v.pk for v in losers]
    request_counts = dict(
        Request.objects.filter(vendor_id__in=loser_pks)
        .values_list("vendor_id")
        .annotate(n=Count("id"))
    )
    item_counts = dict(
        Item.objects.filter(vendor_id__in=loser_pks)
        .values_list("vendor_id")
        .annotate(n=Count("id"))
    )

    moved_requests = Request.objects.filter(vendor_id__in=loser_pks).update(vendor=winner)
    moved_items = Item.objects.filter(vendor_id__in=loser_pks).update(vendor=winner)
    # Delete before renaming, so the winner may take over a loser's exact name without
    # tripping the (lab, name) unique constraint.
    Vendor.objects.filter(pk__in=loser_pks).delete()

    changes = {
        "winner": winner.name,
        "losers": [
            {
                "id": v.pk,
                "name": v.name,
                "requests": request_counts.get(v.pk, 0),
                "items": item_counts.get(v.pk, 0),
            }
            for v in losers
        ],
        "moved_requests": moved_requests,
        "moved_items": moved_items,
    }
    if renaming:
        changes["renamed_from"] = winner.name
        changes["winner"] = new_name
        winner.name = new_name
        winner.save(update_fields=["name", "updated_at"])

    AuditEntry.record(
        lab=lab,
        actor=actor,
        action="lab.suppliers_merged",
        target=winner,
        changes=changes,
    )
    return winner
