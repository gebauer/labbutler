"""Self-service join requests: the shareable "ask to join" link and its review.

Flow: a lab manager enables the lab's join link and shares it. Anyone with the link can
submit their name and email; LabButler emails them a confirmation link, and only once
they confirm does the request reach the lab's managers. A manager approves it with the
roles to grant — which goes through the same path as adding a member by hand (new
accounts get the welcome email with a set-password link) — or rejects it.

Design points:

- **No account until approval.** Submitting creates only a ``JoinRequest`` row.
- **No enumeration.** The public pages answer identically whether the email is new, an
  existing account, or already a member; only the mailbox owner learns more.
- **Abuse limits** are DB-based (so they hold across gunicorn workers): one open
  request per lab+email (a re-submit refreshes it) and a per-lab cap on unconfirmed
  requests per hour.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEntry

from .models import JoinRequest, Lab, Membership, Role, User

Status = JoinRequest.Status

_CONFIRM_SALT = "labbutler.join-request.confirm"
#: Unconfirmed submissions accepted per lab per hour — a flood stops here.
MAX_UNCONFIRMED_PER_HOUR = 20


class JoinError(Exception):
    """A join-flow precondition failed; the message is safe to show to the user."""


# --- The link ----------------------------------------------------------------------------


def enable_join_link(lab: Lab, *, actor) -> str:
    """Turn the link on, or replace its token (revoking every copy of the old link)."""
    action = "lab.join_link_regenerated" if lab.join_token else "lab.join_link_enabled"
    lab.join_token = secrets.token_urlsafe(24)
    lab.save(update_fields=["join_token", "updated_at"])
    AuditEntry.record(lab=lab, actor=actor, action=action, target=lab)
    return lab.join_token


def disable_join_link(lab: Lab, *, actor) -> None:
    lab.join_token = ""
    lab.save(update_fields=["join_token", "updated_at"])
    AuditEntry.record(lab=lab, actor=actor, action="lab.join_link_disabled", target=lab)


def lab_for_token(token: str) -> Lab | None:
    """The lab whose join link uses ``token``, or ``None`` (unknown, revoked, or off)."""
    if not token:
        return None
    return Lab.objects.filter(join_token=token).first()


# --- Submitting and confirming --------------------------------------------------------


@transaction.atomic
def submit(lab: Lab, *, email: str, name: str, message: str = "") -> JoinRequest:
    """Record a join request and email the requester a confirmation link.

    A re-submit for an open request refreshes its name/message (and re-sends the
    confirmation while still unconfirmed) rather than creating a duplicate; one that
    already awaits a manager sends nothing. Raises :class:`JoinError` when the lab's
    hourly cap is reached.
    """
    join_request = (
        JoinRequest.objects.select_for_update()
        .filter(lab=lab, email__iexact=email, status__in=JoinRequest.OPEN_STATUSES)
        .first()
    )
    if join_request is not None:
        join_request.name, join_request.message = name, message
        join_request.save(update_fields=["name", "message", "updated_at"])
    else:
        recent = JoinRequest.objects.filter(
            lab=lab,
            status=Status.UNCONFIRMED,
            created_at__gte=timezone.now() - timedelta(hours=1),
        ).count()
        if recent >= MAX_UNCONFIRMED_PER_HOUR:
            raise JoinError("Too many requests right now — please try again in an hour.")
        join_request = JoinRequest.objects.create(lab=lab, email=email, name=name, message=message)

    if join_request.status == Status.UNCONFIRMED:
        from apps.notifications.tasks import send_join_confirmation

        pk = join_request.pk
        transaction.on_commit(lambda: send_join_confirmation.delay(pk))
    return join_request


def confirmation_token(join_request: JoinRequest) -> str:
    """Signed, expiring token for the confirmation link (bound to the email too)."""
    payload = {"jr": join_request.pk, "e": join_request.email.lower()}
    return signing.dumps(payload, salt=_CONFIRM_SALT)


@transaction.atomic
def confirm(token: str) -> JoinRequest:
    """Confirm the requester's email; the request then reaches the lab's managers.

    Idempotent: confirming again returns the request unchanged. Raises
    :class:`JoinError` for a bad or expired link. If the person turns out to be a member
    already, the request is closed as approved (nothing left to decide).
    """
    try:
        payload = signing.loads(token, salt=_CONFIRM_SALT, max_age=settings.PASSWORD_RESET_TIMEOUT)
    except signing.BadSignature as exc:  # includes SignatureExpired
        raise JoinError("This confirmation link is invalid or has expired.") from exc

    join_request = (
        JoinRequest.objects.select_for_update()
        .select_related("lab")
        .filter(pk=payload.get("jr"), email__iexact=payload.get("e", ""))
        .first()
    )
    if join_request is None:
        raise JoinError("This confirmation link is invalid or has expired.")
    if join_request.status != Status.UNCONFIRMED:
        return join_request

    join_request.confirmed_at = timezone.now()
    if is_member(join_request.lab, join_request.email):
        join_request.status = Status.APPROVED
        join_request.decided_at = join_request.confirmed_at
        join_request.save()
        return join_request

    join_request.status = Status.PENDING
    join_request.save()
    AuditEntry.record(
        lab=join_request.lab,
        action="lab.join_requested",
        target=join_request,
        changes={"email": join_request.email, "name": join_request.name},
    )
    from apps.notifications.tasks import notify_join_request

    pk = join_request.pk
    transaction.on_commit(lambda: notify_join_request.delay(pk))
    return join_request


def is_member(lab: Lab, email: str) -> bool:
    return Membership.objects.filter(lab=lab, user__email__iexact=email).exists()


# --- Manager decisions ----------------------------------------------------------------


def pending_requests(lab: Lab):
    return JoinRequest.objects.filter(lab=lab, status=Status.PENDING).order_by("created_at")


def default_role(lab: Lab) -> Role | None:
    """The role pre-selected when approving: the lab's "Member" role, if it has one."""
    return Role.objects.filter(lab=lab, name="Member", is_template=False).first()


@transaction.atomic
def approve(join_request: JoinRequest, *, actor, roles) -> Membership:
    """Make the requester a member with ``roles`` and tell them.

    New accounts get the standard welcome email (set-password link); people who already
    have an account get a short "you're in" email, since they can sign in right away.
    """
    join_request = _lock_pending(join_request)
    lab = join_request.lab
    user, user_created = User.objects.get_or_create_by_email(
        join_request.email,
        defaults={"username": join_request.email, "friendly_name": join_request.name},
    )
    membership, _ = Membership.objects.get_or_create(user=user, lab=lab)
    membership.roles.set(roles)
    _decide(join_request, Status.APPROVED, actor)
    AuditEntry.record(
        lab=lab,
        actor=actor,
        action="lab.join_request_approved",
        target=membership,
        changes={"email": user.email, "roles": [role.name for role in roles]},
    )

    from apps.notifications.tasks import send_join_decision, send_welcome_email

    user_pk, lab_pk, jr_pk, actor_pk = user.pk, lab.pk, join_request.pk, actor.pk
    if user_created:
        transaction.on_commit(lambda: send_welcome_email.delay(user_pk, lab_pk, actor_pk))
    else:
        transaction.on_commit(lambda: send_join_decision.delay(jr_pk))
    return membership


@transaction.atomic
def reject(join_request: JoinRequest, *, actor) -> None:
    """Decline the request and send the requester a short, neutral note."""
    join_request = _lock_pending(join_request)
    _decide(join_request, Status.REJECTED, actor)
    AuditEntry.record(
        lab=join_request.lab,
        actor=actor,
        action="lab.join_request_rejected",
        target=join_request,
        changes={"email": join_request.email},
    )
    from apps.notifications.tasks import send_join_decision

    jr_pk = join_request.pk
    transaction.on_commit(lambda: send_join_decision.delay(jr_pk))


def _lock_pending(join_request: JoinRequest) -> JoinRequest:
    """Re-read the request under a row lock; refuse if it was decided meanwhile."""
    locked = JoinRequest.objects.select_for_update().select_related("lab").get(pk=join_request.pk)
    if locked.status != Status.PENDING:
        raise JoinError(f"This request was already {locked.get_status_display().lower()}.")
    return locked


def _decide(join_request: JoinRequest, status: str, actor) -> None:
    join_request.status = status
    join_request.decided_by = actor
    join_request.decided_at = timezone.now()
    join_request.save()
