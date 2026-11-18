"""Periodic housekeeping for account data."""

from __future__ import annotations

from datetime import timedelta

from axes.models import AccessFailureLog, AccessLog
from celery import shared_task
from django.conf import settings
from django.utils import timezone


@shared_task
def purge_old_login_records(now=None) -> int:
    """Delete sign-in records (IP address, user agent) older than the retention window.

    django-axes keeps a row per sign-in forever; they are personal data that only serve
    short-term security review, so they get a fixed retention
    (``LABBUTLER_LOGIN_RECORD_RETENTION_DAYS``). Failed-attempt counters are already
    cleared by axes itself once their cool-off expires. Returns the number of deleted rows.
    """
    cutoff = (now or timezone.now()) - timedelta(
        days=settings.LABBUTLER_LOGIN_RECORD_RETENTION_DAYS
    )
    deleted_logs, _ = AccessLog.objects.filter(attempt_time__lt=cutoff).delete()
    deleted_failures, _ = AccessFailureLog.objects.filter(attempt_time__lt=cutoff).delete()
    return deleted_logs + deleted_failures


#: Unconfirmed join requests outlive their confirmation link a little, then go.
UNCONFIRMED_JOIN_REQUEST_DAYS = 7
#: Decided requests are kept briefly for the managers' reference, then go.
DECIDED_JOIN_REQUEST_DAYS = 90


@shared_task
def purge_old_join_requests(now=None) -> int:
    """Delete stale join requests (name, email, message are personal data).

    Unconfirmed ones are dropped after a week, decided ones after 90 days; requests still
    awaiting a manager are kept. The audit log keeps its own record of each decision.
    Returns the number of deleted rows.
    """
    from .models import JoinRequest

    now = now or timezone.now()
    status = JoinRequest.Status
    unconfirmed, _ = JoinRequest.objects.filter(
        status=status.UNCONFIRMED,
        created_at__lt=now - timedelta(days=UNCONFIRMED_JOIN_REQUEST_DAYS),
    ).delete()
    decided, _ = JoinRequest.objects.filter(
        status__in=[status.APPROVED, status.REJECTED],
        updated_at__lt=now - timedelta(days=DECIDED_JOIN_REQUEST_DAYS),
    ).delete()
    return unconfirmed + decided
