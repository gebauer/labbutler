from datetime import timedelta

import pytest
from axes.models import AccessLog
from django.utils import timezone

from apps.tenancy.tasks import purge_old_login_records

pytestmark = pytest.mark.django_db


def _log(when):
    entry = AccessLog.objects.create(
        username="a@x.test", ip_address="10.0.0.1", user_agent="ua", http_accept="*/*"
    )
    # attempt_time is auto_now_add; backdate it explicitly.
    AccessLog.objects.filter(pk=entry.pk).update(attempt_time=when)
    return entry


def test_purges_only_records_older_than_the_retention(settings):
    settings.LABBUTLER_LOGIN_RECORD_RETENTION_DAYS = 90
    now = timezone.now()
    old = _log(now - timedelta(days=91))
    recent = _log(now - timedelta(days=89))

    assert purge_old_login_records(now=now) == 1
    assert not AccessLog.objects.filter(pk=old.pk).exists()
    assert AccessLog.objects.filter(pk=recent.pk).exists()


def test_task_is_scheduled_daily(settings):
    tasks = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert "apps.tenancy.tasks.purge_old_login_records" in tasks
