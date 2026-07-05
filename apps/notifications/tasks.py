"""Celery tasks that resolve recipients, build content, and send notification email.

The effectful edge of notifications: everything DB- or SMTP-touching lives here, while
the message text comes from the pure builders in :mod:`apps.notifications.emails`.
"""

from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.inventory.models import Item
from apps.procurement.models import Request
from apps.tenancy.models import Lab, Membership, NotificationFrequency, User

from . import emails

Frequency = NotificationFrequency


def _base_url() -> str:
    return getattr(settings, "LABBUTLER_BASE_URL", "")


def _send(content: emails.EmailContent, recipients: list[str]) -> None:
    """Send builder output: multipart when an HTML alternative exists, high-priority
    headers when the underlying request is marked urgent (all three header spellings,
    since clients disagree on which one they honour)."""
    headers = (
        {"X-Priority": "1", "Priority": "urgent", "Importance": "high"} if content.urgent else None
    )
    message = EmailMultiAlternatives(
        content.subject, content.body, settings.DEFAULT_FROM_EMAIL, recipients, headers=headers
    )
    if content.html:
        message.attach_alternative(content.html, "text/html")
    message.send()


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
    # On approval with an auto-forward, the coordinator gets the "please order" mail
    # instead of a duplicate "your request is approved" update.
    if new == Request.Status.APPROVED and req.assigned_to and req.assigned_to.email:
        recipients = [email for email in recipients if email != req.assigned_to.email]
    if not recipients:
        return 0
    content = emails.build_status_change(req, previous, new, base_url=_base_url())
    _send(content, recipients)
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
    _send(content, recipients)
    return len(recipients)


@shared_task
def notify_request_assigned(req_pk: int, forwarded_by_pk: int | None = None) -> int:
    """Email the coordinator a request was forwarded to, naming who forwarded it.
    Returns count sent (0/1)."""
    req = (
        Request.objects.select_related("assigned_to", "requested_by", "vendor")
        .filter(pk=req_pk)
        .first()
    )
    if req is None or not req.assigned_to or not req.assigned_to.email:
        return 0
    forwarder = User.objects.filter(pk=forwarded_by_pk).first() if forwarded_by_pk else None
    content = emails.build_assignment(req, forwarded_by=forwarder, base_url=_base_url())
    _send(content, [req.assigned_to.email])
    return 1


@shared_task
def send_welcome_email(user_pk: int, lab_pk: int) -> int:
    """Welcome a freshly-added member with a link to set their password. Returns 0/1.

    Reuses Django's password-reset-confirm route and default token generator, so the link
    works even though the invited user has no usable password yet. The link is absolute via
    ``LABBUTLER_BASE_URL`` (the project's convention for emailed links); with no base URL
    configured it falls back to a relative path.
    """
    user = User.objects.filter(pk=user_pk).first()
    lab = Lab.objects.filter(pk=lab_pk).first()
    if user is None or lab is None or not user.email:
        return 0

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
    base = _base_url()
    url = f"{base.rstrip('/')}{path}" if base else path

    content = emails.build_welcome(user, lab, url)
    _send(content, [user.email])
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
        _send(content, recipients)
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
            _send(content, [user.email])
            emails_sent += 1
    return emails_sent
