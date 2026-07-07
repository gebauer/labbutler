"""Notification task tests: recipient resolution, sending, and the transition hook."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.inventory.models import Item
from apps.notifications import tasks
from apps.notifications.tasks import (
    approval_recipients,
    notify_request_created,
    notify_request_transition,
    request_update_recipients,
    send_expiry_digests,
    send_notification_digests,
    send_welcome_email,
)
from apps.procurement.models import Request
from apps.procurement.services import perform_transition
from apps.tenancy.models import ExpiryReportMode, Membership, NotificationFrequency, User
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
def test_approval_update_skips_the_auto_forwarded_coordinator(lab, mailoutbox):
    member = _user(lab, "req@x.de", ["Member"])
    coord = _user(lab, "coord@x.de", ["Purchase coordinator"])
    req = Request.objects.create(
        lab=lab, item_name="Tips", requested_by=member, assigned_to=coord, status=Status.APPROVED
    )

    # The coordinator just got the "please order" mail, so only the requester is told.
    assert notify_request_transition(req.pk, Status.REQUESTED, Status.APPROVED) == 1
    assert mailoutbox[0].to == ["req@x.de"]
    assert "as you requested" in mailoutbox[0].body

    # On later moves the coordinator is a normal update recipient again.
    assert notify_request_transition(req.pk, Status.APPROVED, Status.ORDERED) == 2
    assert set(mailoutbox[1].to) == {"req@x.de", "coord@x.de"}


@pytest.mark.django_db
def test_notify_task_is_noop_for_missing_request(mailoutbox):
    assert notify_request_transition(999_999, "requested", "approved") == 0
    assert mailoutbox == []


@pytest.mark.django_db
def test_send_expiry_digests_all_mode_reports_expired_and_soon(lab, mailoutbox):
    _user(lab, "mgr@x.de", ["Lab manager"], expiry_notifications=ExpiryReportMode.WEEKLY_ALL)
    today = timezone.localdate()
    Item.objects.create(
        lab=lab, human_id="LB-1", name="OldStock", expiration_date=today - timedelta(days=90)
    )
    Item.objects.create(
        lab=lab, human_id="LB-2", name="Soonish", expiration_date=today + timedelta(days=10)
    )
    Item.objects.create(
        lab=lab, human_id="LB-3", name="Later", expiration_date=today + timedelta(days=90)
    )
    Item.objects.create(lab=lab, human_id="LB-4", name="NoDate")

    assert send_expiry_digests() == 1
    assert len(mailoutbox) == 1
    body = mailoutbox[0].body
    # "All items" mode reports everything expired, however long ago.
    assert "OldStock" in body and "Soonish" in body
    assert "Later" not in body  # beyond the 30-day default window
    assert "NoDate" not in body  # no expiration date


@pytest.mark.django_db
def test_send_expiry_digests_new_mode_lists_only_changes_since_last_week(lab, mailoutbox):
    # WEEKLY_NEW is the default mode: only items that expired, or entered the member's
    # advance window, during the past week appear in the report.
    _user(lab, "mgr@x.de", ["Lab manager"])
    today = timezone.localdate()
    Item.objects.create(
        lab=lab, human_id="LB-1", name="FreshLapse", expiration_date=today - timedelta(days=2)
    )
    Item.objects.create(
        lab=lab, human_id="LB-2", name="LongGone", expiration_date=today - timedelta(days=30)
    )
    Item.objects.create(
        lab=lab, human_id="LB-3", name="JustEntered", expiration_date=today + timedelta(days=27)
    )
    Item.objects.create(
        lab=lab, human_id="LB-4", name="KnownAlready", expiration_date=today + timedelta(days=10)
    )

    assert send_expiry_digests() == 1
    body = mailoutbox[0].body
    assert "FreshLapse" in body and "JustEntered" in body
    assert "LongGone" not in body  # expired long before the last report
    assert "KnownAlready" not in body  # entered the 30-day window weeks ago
    assert "only changes since last week" in body


@pytest.mark.django_db
def test_send_expiry_digests_respects_off(lab, mailoutbox):
    _user(lab, "off@x.de", ["Lab manager"], expiry_notifications=ExpiryReportMode.OFF)
    today = timezone.localdate()
    Item.objects.create(
        lab=lab, human_id="LB-1", name="Expired", expiration_date=today - timedelta(days=1)
    )
    assert send_expiry_digests() == 0
    assert mailoutbox == []


@pytest.mark.django_db
def test_send_expiry_digests_owned_only_limits_to_own_items(lab, mailoutbox):
    owner = _user(
        lab,
        "own@x.de",
        ["Lab manager"],
        expiry_notifications=ExpiryReportMode.WEEKLY_ALL,
        expiry_owned_only=True,
    )
    today = timezone.localdate()
    Item.objects.create(
        lab=lab,
        human_id="LB-1",
        name="Mine",
        expiration_date=today - timedelta(days=1),
        owner=owner,
    )
    Item.objects.create(
        lab=lab, human_id="LB-2", name="Theirs", expiration_date=today - timedelta(days=1)
    )

    assert send_expiry_digests() == 1
    body = mailoutbox[0].body
    assert "Mine" in body
    assert "Theirs" not in body
    assert "items you own" in body


@pytest.mark.django_db
def test_send_expiry_digests_forces_owned_only_without_view_inventory(lab, mailoutbox):
    # A member without view_inventory never receives lab-wide data, even with the
    # owned-only flag off — the report falls back to their own items.
    owner = _user(lab, "norole@x.de", [], expiry_notifications=ExpiryReportMode.WEEKLY_ALL)
    today = timezone.localdate()
    Item.objects.create(
        lab=lab,
        human_id="LB-1",
        name="Mine",
        expiration_date=today - timedelta(days=1),
        owner=owner,
    )
    Item.objects.create(
        lab=lab, human_id="LB-2", name="Theirs", expiration_date=today - timedelta(days=1)
    )

    assert send_expiry_digests() == 1
    assert mailoutbox[0].to == ["norole@x.de"]
    body = mailoutbox[0].body
    assert "Mine" in body
    assert "Theirs" not in body


@pytest.mark.django_db
def test_send_expiry_digests_uses_each_members_advance_window(lab, mailoutbox):
    _user(
        lab,
        "short@x.de",
        ["Lab manager"],
        expiry_notifications=ExpiryReportMode.WEEKLY_ALL,
        expiry_days_ahead=7,
    )
    _user(
        lab,
        "long@x.de",
        ["Lab manager"],
        expiry_notifications=ExpiryReportMode.WEEKLY_ALL,
        expiry_days_ahead=30,
    )
    today = timezone.localdate()
    Item.objects.create(
        lab=lab, human_id="LB-1", name="Soonish", expiration_date=today + timedelta(days=10)
    )

    # Only the member looking 30 days ahead is warned about an item expiring in 10 days.
    assert send_expiry_digests() == 1
    assert mailoutbox[0].to == ["long@x.de"]
    assert "within 30 days" in mailoutbox[0].subject


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
def test_approve_with_auto_forward_mails_requester_and_coordinator(
    lab, mailoutbox, monkeypatch, django_capture_on_commit_callbacks
):
    member = _user(lab, "req@x.de", ["Member"])
    manager = _user(lab, "boss@x.de", ["Lab manager"])
    coord = _user(lab, "coord@x.de", ["Purchase coordinator"])
    req = Request.objects.create(lab=lab, item_name="Tips", requested_by=member, forward_to=coord)
    for task in (tasks.notify_request_transition, tasks.notify_request_assigned):
        monkeypatch.setattr(task, "delay", task)
    with django_capture_on_commit_callbacks(execute=True):
        perform_transition(req, "approve", actor=manager)

    by_recipient = {m.to[0]: m for m in mailoutbox}
    assert set(by_recipient) == {"req@x.de", "coord@x.de"}
    # Requester: approved + handed over as wished. Coordinator: the normal forward mail.
    assert "Approved" in by_recipient["req@x.de"].subject
    assert "as you requested" in by_recipient["req@x.de"].body
    assert "Please order" in by_recipient["coord@x.de"].subject
    assert "boss@x.de has forwarded an approved request" in by_recipient["coord@x.de"].body


@pytest.mark.django_db
def test_notify_request_assigned_emails_the_coordinator(lab, mailoutbox):
    from apps.notifications.tasks import notify_request_assigned
    from apps.procurement.models import Request

    coord = _user(lab, "coord@x.de", ["Purchase coordinator"])
    member = _user(lab, "req@x.de", ["Member"])
    manager = _user(lab, "boss@x.de", ["Lab manager"])
    req = Request.objects.create(
        lab=lab,
        item_name="Pipette tips",
        requested_by=member,
        assigned_to=coord,
        status=Request.Status.APPROVED,
    )
    sent = notify_request_assigned(req.pk, manager.pk)
    assert sent == 1
    mail = mailoutbox[0]
    assert mail.to == ["coord@x.de"]
    assert "Please order" in mail.subject
    # The coordinator learns who forwarded it and who originally asked.
    assert "boss@x.de has forwarded an approved request" in mail.body
    assert "req@x.de" in mail.body
    # Multipart: an HTML alternative rides along; not urgent -> no priority headers.
    assert mail.alternatives and mail.alternatives[0][1] == "text/html"
    assert "X-Priority" not in mail.extra_headers


@pytest.mark.django_db
def test_urgent_mails_carry_priority_headers_and_flagged_subject(lab, mailoutbox):
    from apps.notifications.tasks import notify_request_assigned
    from apps.procurement.models import Request

    coord = _user(lab, "coord@x.de", ["Purchase coordinator"])
    member = _user(lab, "req@x.de", ["Member"])
    _user(lab, "boss@x.de", ["Lab manager"])
    req = Request.objects.create(
        lab=lab,
        item_name="Dry ice",
        requested_by=member,
        assigned_to=coord,
        is_urgent=True,
    )

    assert notify_request_created(req.pk) == 1
    assert notify_request_assigned(req.pk, member.pk) == 1
    for mail in mailoutbox:
        assert "URGENT" in mail.subject
        assert "URGENT" in mail.body
        assert mail.extra_headers["X-Priority"] == "1"
        assert mail.extra_headers["Importance"] == "high"


@pytest.mark.django_db
def test_notify_request_assigned_noop_without_assignee(mailoutbox):
    from apps.notifications.tasks import notify_request_assigned

    assert notify_request_assigned(999_999) == 0
    assert mailoutbox == []


@pytest.mark.django_db
def test_send_welcome_email_links_a_valid_set_password_token(lab, mailoutbox, settings):
    from urllib.parse import urlparse

    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_decode

    settings.LABBUTLER_BASE_URL = "https://lab.example.org"
    # An invited member: created without a usable password, mirroring member_add.
    user = User.objects.create_user(username="", email="new@x.de")

    assert send_welcome_email(user.pk, lab.pk) == 1
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["new@x.de"]
    assert lab.name in mailoutbox[0].subject

    # The emailed link must carry a token that Django will accept for this user, even though
    # the account has no usable password yet.
    link = next(w for w in mailoutbox[0].body.split() if w.startswith("https://"))
    assert link.startswith("https://lab.example.org/")
    parts = urlparse(link).path.strip("/").split("/")
    uidb64, token = parts[-2], parts[-1]
    assert urlsafe_base64_decode(uidb64).decode() == str(user.pk)
    assert default_token_generator.check_token(user, token)


@pytest.mark.django_db
def test_send_welcome_email_is_noop_for_missing_user_or_email(lab, mailoutbox):
    assert send_welcome_email(999_999, lab.pk) == 0
    # Bypass the manager's email requirement to exercise the task's defensive guard.
    no_email = User.objects.create(username="noemail", email="")
    assert send_welcome_email(no_email.pk, lab.pk) == 0
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
