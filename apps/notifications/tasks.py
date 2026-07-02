"""Celery tasks that resolve recipients, build content, and send notification email.

The effectful edge of notifications: everything DB- or SMTP-touching lives here, while
the message text comes from the pure builders in :mod:`apps.notifications.emails`.
"""

from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.inventory.models import Item
from apps.procurement.models import Request
from apps.tenancy.models import Lab, Membership, NotificationFrequency, User

from . import emails

Frequency = NotificationFrequency


def _base_url() -> str:
    return getattr(settings, "LABBUTLER_BASE_URL", "")


def _frequency(user: User, lab: Lab, field: str) -> str:
    """A user's chosen frequency for preference ``field`` in ``lab``.

    Falls back to IMMEDIATE ("every email") when there is no membership, preserving the
    default-on behaviour for edge cases such as stub users on imported data.
    """
    membership = Membership.objects.filter(user=user, lab=lab).only(field).first()
    return getattr(membership, field) if membership else Frequency.IMMEDIATE


def request_update_recipients(req: Request, *, frequency: str = Frequency.IMMEDIATE) -> list[str]:
    """Emails of the requester and the orderer (assignee), when set, who want status-update
    email at ``frequency``. The approver is excluded — they acted on it, so they don't get
    "your request" updates."""
    people = {req.requested_by, req.assigned_to}
    return sorted(
        {
            user.email
            for user in people
            if user
            and user.email
            and _frequency(user, req.lab, "request_update_notifications") == frequency
        }
    )


def approval_recipients(
    lab: Lab, *, frequency: str = Frequency.IMMEDIATE, exclude: User | None = None
) -> list[str]:
    """Emails of members who can approve requests in ``lab`` and want approval email at
    ``frequency`` (optionally excluding one user, e.g. the requester themselves)."""
    users = (
        User.objects.filter(
            memberships__lab=lab,
            memberships__roles__permissions__code="approve_request",
            memberships__approval_notifications=frequency,
        )
        .exclude(email="")
        .distinct()
    )
    if exclude is not None:
        users = users.exclude(pk=exclude.pk)
    return sorted({user.email for user in users})


def digest_recipients(lab: Lab) -> list[str]:
    """Emails of lab members who can manage inventory — the people who act on expiry."""
    users = (
        User.objects.filter(
            memberships__lab=lab,
            memberships__roles__permissions__code="manage_inventory",
        )
        .exclude(email="")
        .distinct()
    )
    return sorted({user.email for user in users})


@shared_task
def notify_request_transition(req_pk: int, previous: str, new: str) -> int:
    """Email the requester/orderer that request ``req_pk`` changed status. Returns count sent."""
    req = (
        Request.objects.select_related("requested_by", "assigned_to", "vendor", "created_item")
        .filter(pk=req_pk)
        .first()
    )
    if req is None:
        return 0
    recipients = request_update_recipients(req)
    if not recipients:
        return 0
    content = emails.build_status_change(req, previous, new, base_url=_base_url())
    send_mail(content.subject, content.body, settings.DEFAULT_FROM_EMAIL, recipients)
    return len(recipients)


@shared_task
def notify_request_created(req_pk: int) -> int:
    """Email the lab's approvers that a new request ``req_pk`` awaits approval.

    Skips the requester (no "approve your own request" mail) and anyone whose approval
    preference isn't immediate. Returns the number of approvers emailed.
    """
    req = Request.objects.select_related("requested_by", "vendor").filter(pk=req_pk).first()
    if req is None:
        return 0
    recipients = approval_recipients(req.lab, exclude=req.requested_by)
    if not recipients:
        return 0
    content = emails.build_approval_needed(req, base_url=_base_url())
    send_mail(content.subject, content.body, settings.DEFAULT_FROM_EMAIL, recipients)
    return len(recipients)


@shared_task
def notify_request_assigned(req_pk: int) -> int:
    """Email the coordinator a request was forwarded to. Returns count sent (0/1)."""
    req = Request.objects.select_related("assigned_to", "vendor").filter(pk=req_pk).first()
    if req is None or not req.assigned_to or not req.assigned_to.email:
        return 0
    content = emails.build_assignment(req, base_url=_base_url())
    send_mail(content.subject, content.body, settings.DEFAULT_FROM_EMAIL, [req.assigned_to.email])
    return 1


@shared_task
def send_expiry_digests(days_ahead: int | None = None) -> int:
    """Send a per-lab digest of expired / soon-to-expire items. Returns labs notified."""
    if days_ahead is None:
        days_ahead = getattr(settings, "EXPIRY_DIGEST_DAYS", 30)
    today = timezone.localdate()
    horizon = today + timedelta(days=days_ahead)

    labs_notified = 0
    for lab in Lab.objects.all():
        items = list(
            Item.objects.filter(
                lab=lab, expiration_date__isnull=False, expiration_date__lte=horizon
            )
            .select_related("location")
            .order_by("expiration_date")
        )
        if not items:
            continue
        recipients = digest_recipients(lab)
        if not recipients:
            continue
        expired = [i for i in items if i.expiration_date < today]
        expiring = [i for i in items if i.expiration_date >= today]
        content = emails.build_expiry_digest(
            lab, expired, expiring, today, days_ahead=days_ahead, base_url=_base_url()
        )
        send_mail(content.subject, content.body, settings.DEFAULT_FROM_EMAIL, recipients)
        labs_notified += 1
    return labs_notified


@shared_task
def send_notification_digests(since=None) -> int:
    """Send each member their daily procurement digest. Returns the number of emails sent.

    Bundles, per lab and per member who opted into a daily summary: requests awaiting their
    approval (for approvers) and their own requests updated since ``since`` (default 24h).
    Members set to immediate/off for a category are omitted from that section; a member with
    nothing to report gets no email.
    """
    since = since or (timezone.now() - timedelta(days=1))
    today = timezone.localdate()
    emails_sent = 0

    for lab in Lab.objects.all():
        pending = list(
            Request.objects.filter(lab=lab, status=Request.Status.REQUESTED).order_by("created_at")
        )
        recent = list(
            Request.objects.filter(lab=lab, updated_at__gte=since)
            .exclude(status=Request.Status.REQUESTED)
            .select_related("requested_by", "assigned_to")
        )
        memberships = Membership.objects.filter(lab=lab).select_related("user")
        for membership in memberships:
            user = membership.user
            if not user.email:
                continue

            approvals = []
            if membership.approval_notifications == Frequency.DAILY and user.can(
                lab, "approve_request"
            ):
                approvals = [r for r in pending if r.requested_by_id != user.pk]

            updates = []
            if membership.request_update_notifications == Frequency.DAILY:
                updates = [r for r in recent if user.pk in (r.requested_by_id, r.assigned_to_id)]

            if not approvals and not updates:
                continue
            content = emails.build_daily_digest(
                lab, approvals, updates, today, base_url=_base_url()
            )
            send_mail(content.subject, content.body, settings.DEFAULT_FROM_EMAIL, [user.email])
            emails_sent += 1
    return emails_sent
