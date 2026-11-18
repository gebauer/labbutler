"""Self-service join requests: link lifecycle, public form, confirmation, decisions."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEntry
from apps.tenancy import join
from apps.tenancy.models import JoinRequest, Membership, Role, User
from apps.tenancy.services import add_member, create_lab
from apps.tenancy.tasks import purge_old_join_requests
from labbutler import dashboard

pytestmark = pytest.mark.django_db
Status = JoinRequest.Status


@pytest.fixture
def lab(db):
    return create_lab(name="AG Join", item_id_prefix="JN")


@pytest.fixture
def manager(lab):
    user = User.objects.create_user(username="", email="boss@x.de", password="pw")
    add_member(user=user, lab=lab, role_names=["Lab manager"])
    return user


@pytest.fixture
def join_url(lab, manager):
    token = join.enable_join_link(lab, actor=manager)
    return reverse("tenancy:join_request", args=[token])


@pytest.fixture
def on_commit(django_capture_on_commit_callbacks):
    """Run on-commit callbacks (the email tasks) as the real request cycle would."""

    def run():
        return django_capture_on_commit_callbacks(execute=True)

    return run


def _ask(client, url, email="new@x.de", **extra):
    data = {"name": "Nina Neu", "email": email, "message": "PhD student", **extra}
    return client.post(url, data)


def _confirm_link(mail) -> str:
    return next(word for word in mail.body.split() if "/join/confirm/" in word)


def _submit_and_confirm(client, join_url, on_commit, mailoutbox, email="new@x.de"):
    with on_commit():
        _ask(client, join_url, email=email)
    with on_commit():
        client.get(_confirm_link(mailoutbox[-1]))
    return JoinRequest.objects.get(email=email)


# --- The link ---------------------------------------------------------------------------


def test_join_page_is_404_while_the_link_is_off(client, lab):
    resp = client.get(reverse("tenancy:join_request", args=["nope"]))
    assert resp.status_code == 404
    assert "doesn't work" in resp.content.decode()


def test_regenerating_revokes_the_old_link(client, lab, manager, join_url):
    join.enable_join_link(lab, actor=manager)
    assert client.get(join_url).status_code == 404


def test_disabling_turns_the_link_off(client, lab, manager, join_url):
    join.disable_join_link(lab, actor=manager)
    assert client.get(join_url).status_code == 404


def test_manager_creates_the_link_from_the_members_page(client, lab, manager):
    client.force_login(manager)
    client.post(reverse("manage:join_link"), {"action": "enable"})
    lab.refresh_from_db()
    assert lab.join_token
    page = client.get(reverse("manage:members")).content.decode()
    assert f"/join/{lab.join_token}/" in page


def test_non_manager_cannot_change_the_link(client, lab):
    member = User.objects.create_user(username="", email="m@x.de", password="pw")
    add_member(user=member, lab=lab, role_names=["Member"])
    client.force_login(member)
    assert client.post(reverse("manage:join_link"), {"action": "enable"}).status_code == 403


# --- Submitting --------------------------------------------------------------------------


def test_submission_sends_a_confirmation_but_reaches_no_manager_yet(
    client, join_url, on_commit, mailoutbox
):
    with on_commit():
        resp = _ask(client, join_url)

    assert "Check your inbox" in resp.content.decode()
    assert JoinRequest.objects.get().status == Status.UNCONFIRMED
    assert [m.to for m in mailoutbox] == [["new@x.de"]]
    assert "/join/confirm/" in mailoutbox[0].body
    assert not User.objects.filter(email="new@x.de").exists()


def test_resubmitting_refreshes_instead_of_duplicating(client, join_url, on_commit, mailoutbox):
    with on_commit():
        _ask(client, join_url)
        _ask(client, join_url, email="NEW@x.de", message="second try")

    request = JoinRequest.objects.get()
    assert request.message == "second try"
    assert len(mailoutbox) == 2  # the confirmation is re-sent


def test_honeypot_submission_is_dropped_silently(client, join_url, on_commit, mailoutbox):
    with on_commit():
        resp = _ask(client, join_url, website="http://spam.example")
    assert "Check your inbox" in resp.content.decode()
    assert not JoinRequest.objects.exists()
    assert mailoutbox == []


def test_existing_member_gets_the_same_answer(client, join_url, manager, on_commit, mailoutbox):
    """No account enumeration: the page reads the same for an existing member."""
    resp = _ask(client, join_url, email=manager.email)
    assert "Check your inbox" in resp.content.decode()


def test_hourly_cap_stops_a_flood(client, lab, join_url, monkeypatch):
    monkeypatch.setattr(join, "MAX_UNCONFIRMED_PER_HOUR", 2)
    _ask(client, join_url, email="a@x.de")
    _ask(client, join_url, email="b@x.de")
    resp = _ask(client, join_url, email="c@x.de")
    assert "Too many requests" in resp.content.decode()
    assert JoinRequest.objects.count() == 2


# --- Confirming --------------------------------------------------------------------------


def test_confirming_notifies_the_managers(client, lab, join_url, on_commit, mailoutbox):
    request = _submit_and_confirm(client, join_url, on_commit, mailoutbox)

    assert request.status == Status.PENDING
    assert mailoutbox[-1].to == ["boss@x.de"]
    assert "Nina Neu asks to join AG Join" in mailoutbox[-1].subject
    assert AuditEntry.objects.filter(action="lab.join_requested", lab=lab).exists()


def test_confirming_twice_is_harmless(client, join_url, on_commit, mailoutbox):
    _submit_and_confirm(client, join_url, on_commit, mailoutbox)
    sent = len(mailoutbox)
    link = next(_confirm_link(m) for m in mailoutbox if m.subject.startswith("[LabButler] Confirm"))
    with on_commit():
        resp = client.get(link)
    assert resp.status_code == 200
    assert len(mailoutbox) == sent  # managers aren't notified again


def test_tampered_or_expired_link_is_refused(client, join_url, on_commit, mailoutbox, settings):
    with on_commit():
        _ask(client, join_url)
    link = _confirm_link(mailoutbox[0])

    assert client.get(link.replace("/join/confirm/", "/join/confirm/x")).status_code == 400
    settings.PASSWORD_RESET_TIMEOUT = -1  # every token is now older than allowed
    assert client.get(link).status_code == 400
    assert JoinRequest.objects.get().status == Status.UNCONFIRMED


def test_existing_member_confirming_is_told_to_sign_in(
    client, join_url, manager, on_commit, mailoutbox
):
    request = _submit_and_confirm(client, join_url, on_commit, mailoutbox, email=manager.email)
    assert request.status == Status.APPROVED
    assert not any("asks to join" in m.subject for m in mailoutbox)


# --- Deciding ----------------------------------------------------------------------------


def test_only_confirmed_requests_are_listed_for_managers(client, lab, manager, join_url):
    _ask(client, join_url)
    client.force_login(manager)
    assert "Nina Neu" not in client.get(reverse("manage:members")).content.decode()


def test_approving_creates_the_member_with_roles_and_welcomes_them(
    client, lab, manager, join_url, on_commit, mailoutbox
):
    request = _submit_and_confirm(client, join_url, on_commit, mailoutbox)
    client.force_login(manager)
    page = client.get(reverse("manage:members")).content.decode()
    assert "Nina Neu" in page and "PhD student" in page

    member_role = Role.objects.get(lab=lab, name="Member")
    with on_commit():
        client.post(
            reverse("manage:join_approve", args=[request.pk]),
            {f"jr{request.pk}-roles": [member_role.pk]},
        )

    user = User.objects.get(email="new@x.de")
    assert user.friendly_name == "Nina Neu"
    assert list(Membership.objects.get(user=user, lab=lab).roles.all()) == [member_role]
    assert mailoutbox[-1].subject == "[LabButler] Welcome to AG Join"
    request.refresh_from_db()
    assert request.status == Status.APPROVED and request.decided_by == manager


def test_approving_an_existing_account_sends_the_approved_note(
    client, lab, manager, join_url, on_commit, mailoutbox
):
    other_lab = create_lab(name="AG Other", item_id_prefix="OT")
    existing = User.objects.create_user(username="", email="known@x.de", password="pw")
    add_member(user=existing, lab=other_lab, role_names=["Member"])
    request = _submit_and_confirm(client, join_url, on_commit, mailoutbox, email="known@x.de")

    client.force_login(manager)
    with on_commit():
        client.post(reverse("manage:join_approve", args=[request.pk]), {})

    assert Membership.objects.filter(user=existing, lab=lab).exists()
    assert mailoutbox[-1].subject == "[LabButler] You're now a member of AG Join"


def test_rejecting_sends_a_neutral_note_once(client, manager, join_url, on_commit, mailoutbox):
    request = _submit_and_confirm(client, join_url, on_commit, mailoutbox)
    client.force_login(manager)
    with on_commit():
        client.post(reverse("manage:join_reject", args=[request.pk]))
        client.post(reverse("manage:join_reject", args=[request.pk]))  # double click

    request.refresh_from_db()
    assert request.status == Status.REJECTED
    assert sum("Your request to join" in m.subject for m in mailoutbox) == 1
    assert not User.objects.filter(email="new@x.de").exists()


def test_requests_of_other_labs_are_out_of_reach(client, join_url, on_commit, mailoutbox):
    request = _submit_and_confirm(client, join_url, on_commit, mailoutbox)
    outsider_lab = create_lab(name="AG Else", item_id_prefix="EL")
    outsider = User.objects.create_user(username="", email="o@x.de", password="pw")
    add_member(user=outsider, lab=outsider_lab, role_names=["Lab manager"])
    client.force_login(outsider)

    resp = client.post(reverse("manage:join_approve", args=[request.pk]), {})
    assert resp.status_code == 404


def test_dashboard_shows_pending_requests_to_managers(
    client, lab, manager, join_url, on_commit, mailoutbox
):
    assert "join_requests" not in [w.key for w in dashboard.build(manager, lab)]
    _submit_and_confirm(client, join_url, on_commit, mailoutbox)
    widget = next(w for w in dashboard.build(manager, lab) if w.key == "join_requests")
    assert widget.total == 1


# --- Retention ---------------------------------------------------------------------------


def test_stale_requests_are_purged_but_pending_ones_kept(lab):
    now = timezone.now()

    def make(email, status, age_days):
        request = JoinRequest.objects.create(lab=lab, email=email, name="x", status=status)
        then = now - timedelta(days=age_days)
        JoinRequest.objects.filter(pk=request.pk).update(created_at=then, updated_at=then)

    make("old-unconfirmed@x.de", Status.UNCONFIRMED, 8)
    make("fresh-unconfirmed@x.de", Status.UNCONFIRMED, 2)
    make("old-pending@x.de", Status.PENDING, 200)
    make("old-rejected@x.de", Status.REJECTED, 91)
    make("recent-approved@x.de", Status.APPROVED, 30)

    assert purge_old_join_requests(now=now) == 2
    assert set(JoinRequest.objects.values_list("email", flat=True)) == {
        "fresh-unconfirmed@x.de",
        "old-pending@x.de",
        "recent-approved@x.de",
    }
