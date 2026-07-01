"""Notification task tests: recipient resolution, sending, and the transition hook."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.inventory.models import Item
from apps.notifications import tasks
from apps.notifications.tasks import (
    digest_recipients,
    notify_request_transition,
    send_expiry_digests,
    status_change_recipients,
)
from apps.procurement.models import Request
from apps.procurement.services import perform_transition
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab

Status = Request.Status


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="LB")


def _user(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


@pytest.mark.django_db
def test_status_change_recipients_dedupe(lab):
    person = _user(lab, "a@x.de", ["Member"])
    req = Request.objects.create(lab=lab, item_name="X", requested_by=person, approver=person)
    assert status_change_recipients(req) == ["a@x.de"]


@pytest.mark.django_db
def test_notify_task_emails_everyone_involved(lab, mailoutbox):
    member = _user(lab, "req@x.de", ["Member"])
    manager = _user(lab, "boss@x.de", ["Lab manager"])
    req = Request.objects.create(lab=lab, item_name="Tips", requested_by=member, approver=manager)
    sent = notify_request_transition(req.pk, Status.REQUESTED, Status.APPROVED)
    assert sent == 2
    assert len(mailoutbox) == 1
    assert set(mailoutbox[0].to) == {"req@x.de", "boss@x.de"}
    assert "Approved" in mailoutbox[0].subject


@pytest.mark.django_db
def test_notify_task_is_noop_for_missing_request(mailoutbox):
    assert notify_request_transition(999_999, "requested", "approved") == 0
    assert mailoutbox == []


@pytest.mark.django_db
def test_digest_recipients_are_inventory_managers_only(lab):
    _user(lab, "mgr@x.de", ["Lab manager"])  # manage_inventory via "*"
    _user(lab, "member@x.de", ["Member"])  # Member carries manage_inventory
    _user(lab, "viewer@x.de", ["Viewer"])  # view-only -> excluded
    assert digest_recipients(lab) == ["member@x.de", "mgr@x.de"]


@pytest.mark.django_db
def test_send_expiry_digests_reports_expired_and_soon(lab, mailoutbox, settings):
    settings.EXPIRY_DIGEST_DAYS = 30
    _user(lab, "mgr@x.de", ["Lab manager"])
    today = timezone.localdate()
    Item.objects.create(
        lab=lab, human_id="LB-1", name="Expired", expiration_date=today - timedelta(days=5)
    )
    Item.objects.create(
        lab=lab, human_id="LB-2", name="Soon", expiration_date=today + timedelta(days=10)
    )
    Item.objects.create(
        lab=lab, human_id="LB-3", name="Later", expiration_date=today + timedelta(days=90)
    )
    Item.objects.create(lab=lab, human_id="LB-4", name="NoDate")

    assert send_expiry_digests() == 1
    assert len(mailoutbox) == 1
    body = mailoutbox[0].body
    assert "Expired" in body and "Soon" in body
    assert "Later" not in body  # beyond the horizon
    assert "NoDate" not in body  # no expiration date


@pytest.mark.django_db
def test_send_expiry_digests_skips_labs_without_recipients(lab, mailoutbox):
    today = timezone.localdate()
    Item.objects.create(
        lab=lab, human_id="LB-1", name="Expired", expiration_date=today - timedelta(days=1)
    )
    # No member can manage inventory, so there's no one to notify.
    assert send_expiry_digests() == 0
    assert mailoutbox == []


@pytest.mark.django_db
def test_perform_transition_enqueues_notification_on_commit(
    lab, mailoutbox, monkeypatch, django_capture_on_commit_callbacks
):
    member = _user(lab, "req@x.de", ["Member"])
    manager = _user(lab, "boss@x.de", ["Lab manager"])
    req = Request.objects.create(lab=lab, item_name="Tips", requested_by=member)
    # Run the enqueued task inline instead of dispatching to a Celery worker.
    monkeypatch.setattr(
        tasks.notify_request_transition,
        "delay",
        lambda *args, **kwargs: tasks.notify_request_transition(*args, **kwargs),
    )
    with django_capture_on_commit_callbacks(execute=True):
        perform_transition(req, "approve", actor=manager)

    assert len(mailoutbox) == 1
    assert "req@x.de" in mailoutbox[0].to
    assert "Approved" in mailoutbox[0].subject
