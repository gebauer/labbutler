"""Notification task tests: recipient resolution, sending, and the transition hook."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.inventory.models import Item
from apps.notifications import tasks
from apps.notifications.tasks import (
    approval_recipients,
    digest_recipients,
    notify_request_created,
    notify_request_transition,
    request_update_recipients,
    send_expiry_digests,
    send_notification_digests,
)
from apps.procurement.models import Request
from apps.procurement.services import perform_transition
from apps.tenancy.models import Membership, NotificationFrequency, User
from apps.tenancy.services import add_member, create_lab

Status = Request.Status
Frequency = NotificationFrequency


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="LB")


def _user(lab, email: str, roles: list[str], **prefs) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    membership = add_member(user=user, lab=lab, role_names=roles)
    if prefs:
        Membership.objects.filter(pk=membership.pk).update(**prefs)
    return user


@pytest.mark.django_db
def test_request_update_recipients_are_requester_and_orderer_not_approver(lab):
    member = _user(lab, "req@x.de", ["Member"])
    coord = _user(lab, "coord@x.de", ["Purchase coordinator"])
    approver = _user(lab, "boss@x.de", ["Lab manager"])
    req = Request.objects.create(
        lab=lab, item_name="X", requested_by=member, assigned_to=coord, approver=approver
    )
    # Requester + orderer, but not the approver.
    assert request_update_recipients(req) == ["coord@x.de", "req@x.de"]


@pytest.mark.django_db
def test_request_update_recipients_respect_off_preference(lab):
    member = _user(lab, "req@x.de", ["Member"], request_update_notifications=Frequency.OFF)
    req = Request.objects.create(lab=lab, item_name="X", requested_by=member)
    assert request_update_recipients(req) == []


@pytest.mark.django_db
def test_notify_task_emails_requester_and_orderer(lab, mailoutbox):
    member = _user(lab, "req@x.de", ["Member"])
    coord = _user(lab, "coord@x.de", ["Purchase coordinator"])
    req = Request.objects.create(lab=lab, item_name="Tips", requested_by=member, assigned_to=coord)
    sent = notify_request_transition(req.pk, Status.ORDERED, Status.DELIVERED)
    assert sent == 2
    assert len(mailoutbox) == 1
    assert set(mailoutbox[0].to) == {"req@x.de", "coord@x.de"}
    assert "Delivered" in mailoutbox[0].subject


@pytest.mark.django_db
def test_approval_recipients_respect_pref_and_exclude_requester(lab):
    approver = _user(lab, "boss@x.de", ["Lab manager"])
    _user(lab, "silent@x.de", ["Lab manager"], approval_notifications=Frequency.OFF)
    # A manager who is also the requester shouldn't be asked to approve their own request.
    assert approval_recipients(lab) == ["boss@x.de"]
    assert approval_recipients(lab, exclude=approver) == []


@pytest.mark.django_db
def test_notify_request_created_emails_immediate_approvers_only(lab, mailoutbox):
    member = _user(lab, "req@x.de", ["Member"])
    _user(lab, "boss@x.de", ["Lab manager"])
    _user(lab, "silent@x.de", ["Lab manager"], approval_notifications=Frequency.OFF)
    _user(lab, "daily@x.de", ["Lab manager"], approval_notifications=Frequency.DAILY)
    req = Request.objects.create(lab=lab, item_name="Tips", requested_by=member)

    sent = notify_request_created(req.pk)
    assert sent == 1
    assert mailoutbox[0].to == ["boss@x.de"]
    assert "Approval needed" in mailoutbox[0].subject


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


@pytest.mark.django_db
def test_notify_request_assigned_emails_the_coordinator(lab, mailoutbox):
    from apps.notifications.tasks import notify_request_assigned
    from apps.procurement.models import Request

    coord = _user(lab, "coord@x.de", ["Purchase coordinator"])
    member = _user(lab, "req@x.de", ["Member"])
    req = Request.objects.create(
        lab=lab,
        item_name="Pipette tips",
        requested_by=member,
        assigned_to=coord,
        status=Request.Status.APPROVED,
    )
    sent = notify_request_assigned(req.pk)
    assert sent == 1
    assert mailoutbox[0].to == ["coord@x.de"]
    assert "Please order" in mailoutbox[0].subject


@pytest.mark.django_db
def test_notify_request_assigned_noop_without_assignee(mailoutbox):
    from apps.notifications.tasks import notify_request_assigned

    assert notify_request_assigned(999_999) == 0
    assert mailoutbox == []


@pytest.mark.django_db
def test_send_notification_digests_bundles_approvals_and_updates(lab, mailoutbox):
    boss = _user(lab, "boss@x.de", ["Lab manager"], approval_notifications=Frequency.DAILY)
    member = _user(lab, "req@x.de", ["Member"], request_update_notifications=Frequency.DAILY)
    other = _user(lab, "other@x.de", ["Member"])  # all-immediate -> no digest

    Request.objects.create(
        lab=lab, item_name="Pending thing", requested_by=other, status=Status.REQUESTED
    )
    Request.objects.create(
        lab=lab, item_name="My thing", requested_by=member, status=Status.ORDERED
    )

    sent = send_notification_digests()

    assert sent == 2
    by_recipient = {m.to[0]: m for m in mailoutbox}
    assert set(by_recipient) == {"boss@x.de", "req@x.de"}
    assert "Pending thing" in by_recipient["boss@x.de"].body  # approver's queue
    assert "My thing" in by_recipient["req@x.de"].body  # requester's update
    assert boss.email not in by_recipient["req@x.de"].body


@pytest.mark.django_db
def test_send_notification_digests_skips_approver_own_pending(lab, mailoutbox):
    # A manager on daily approvals who has nothing else pending shouldn't be emailed about
    # a request they raised themselves.
    boss = _user(lab, "boss@x.de", ["Lab manager"], approval_notifications=Frequency.DAILY)
    Request.objects.create(
        lab=lab, item_name="Own request", requested_by=boss, status=Status.REQUESTED
    )
    assert send_notification_digests() == 0
    assert mailoutbox == []
