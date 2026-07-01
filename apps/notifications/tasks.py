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
from apps.tenancy.models import Lab, User

from . import emails


def _base_url() -> str:
    return getattr(settings, "LABBUTLER_BASE_URL", "")


def status_change_recipients(req: Request) -> list[str]:
    """Emails of the people involved in a request (requester, approver, assignee)."""
    people = {req.requested_by, req.approver, req.assigned_to}
    return sorted({user.email for user in people if user and user.email})


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
    """Email the people involved that request ``req_pk`` changed status. Returns count sent."""
    req = (
        Request.objects.select_related(
            "requested_by", "approver", "assigned_to", "vendor", "created_item"
        )
        .filter(pk=req_pk)
        .first()
    )
    if req is None:
        return 0
    recipients = status_change_recipients(req)
    if not recipients:
        return 0
    content = emails.build_status_change(req, previous, new, base_url=_base_url())
    send_mail(content.subject, content.body, settings.DEFAULT_FROM_EMAIL, recipients)
    return len(recipients)


@shared_task
def notify_request_assigned(req_pk: int) -> int:
    """Email the coordinator a request was forwarded to. Returns count sent (0/1)."""
    req = (
        Request.objects.select_related("assigned_to", "vendor").filter(pk=req_pk).first()
    )
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
