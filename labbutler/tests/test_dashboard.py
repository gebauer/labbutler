"""Home dashboard: role-gated widgets and dashboard-returning direct actions."""

import pytest
from django.urls import reverse

from apps.procurement.models import Request
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab

Status = Request.Status


@pytest.fixture
def lab(db):
    return create_lab(name="Dash Lab", item_id_prefix="LB")


def _user(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


@pytest.mark.django_db
def test_dashboard_shows_approvals_for_approvers(client, lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    Request.objects.create(
        lab=lab, item_name="Pipettes", requested_by=member, status=Status.REQUESTED
    )
    client.force_login(manager)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    assert b"Requests to approve" in resp.content
    assert b"Pipettes" in resp.content and b"Approve" in resp.content


@pytest.mark.django_db
def test_dashboard_is_empty_for_viewer(client, lab):
    client.force_login(_user(lab, "v@x.de", ["Viewer"]))
    resp = client.get(reverse("home"))
    assert b"Nothing needs your attention" in resp.content
    assert b"Requests to approve" not in resp.content


@pytest.mark.django_db
def test_forwarded_widget_lists_requests_assigned_to_me(client, lab):
    coord = _user(lab, "c@x.de", ["Purchase coordinator"])
    member = _user(lab, "u@x.de", ["Member"])
    Request.objects.create(
        lab=lab,
        item_name="Assigned to me",
        requested_by=member,
        assigned_to=coord,
        status=Status.APPROVED,
    )
    client.force_login(coord)
    resp = client.get(reverse("home"))
    assert b"Forwarded to you to order" in resp.content
    assert b"Assigned to me" in resp.content


@pytest.mark.django_db
def test_direct_approve_returns_to_dashboard(client, lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = Request.objects.create(
        lab=lab, item_name="Tips", requested_by=member, status=Status.REQUESTED
    )
    client.force_login(manager)
    resp = client.post(
        reverse("procurement:request_action", args=[req.pk, "approve"]), {"next": "/"}
    )
    assert resp.status_code == 302
    assert resp["Location"] == "/"
    req.refresh_from_db()
    assert req.status == Status.APPROVED


@pytest.mark.django_db
def test_offsite_next_is_ignored(client, lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = Request.objects.create(
        lab=lab, item_name="Tips", requested_by=member, status=Status.REQUESTED
    )
    client.force_login(manager)
    resp = client.post(
        reverse("procurement:request_action", args=[req.pk, "approve"]),
        {"next": "http://evil.example.com/"},
    )
    assert reverse("procurement:request_detail", args=[req.pk]) in resp["Location"]


@pytest.mark.django_db
def test_forwarded_widget_hidden_for_non_coordinator(client, lab):
    # A manager has place_order (via "*") but isn't in the Purchase coordinator role.
    client.force_login(_user(lab, "m@x.de", ["Lab manager"]))
    resp = client.get(reverse("home"))
    assert b"Forwarded to you to order" not in resp.content


@pytest.mark.django_db
def test_my_pending_requests_scope(lab):
    from labbutler import dashboard

    member = _user(lab, "u@x.de", ["Member"])
    coord = _user(lab, "c@x.de", ["Purchase coordinator"])
    Request.objects.create(
        lab=lab, item_name="Awaiting", requested_by=member, status=Status.REQUESTED
    )
    Request.objects.create(
        lab=lab, item_name="Approved open", requested_by=member, status=Status.APPROVED
    )
    Request.objects.create(
        lab=lab,
        item_name="Approved forwarded",
        requested_by=member,
        status=Status.APPROVED,
        assigned_to=coord,
    )
    Request.objects.create(
        lab=lab, item_name="Already ordered", requested_by=member, status=Status.ORDERED
    )

    widgets = {w.key: w for w in dashboard.build(member, lab)}
    pending = widgets["my_requests"]
    assert pending.title == "My pending requests"
    # Awaiting approval + approved-but-not-forwarded; excludes forwarded and ordered.
    assert {r.item_name for r in pending.items} == {"Awaiting", "Approved open"}
