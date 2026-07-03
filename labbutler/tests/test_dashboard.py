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
def test_order_widget_lists_unassigned_and_my_forwarded_requests(client, lab):
    coord = _user(lab, "c@x.de", ["Purchase coordinator"])
    other_coord = _user(lab, "c2@x.de", ["Purchase coordinator"])
    member = _user(lab, "u@x.de", ["Member"])
    Request.objects.create(
        lab=lab,
        item_name="Assigned to me",
        requested_by=member,
        assigned_to=coord,
        status=Status.APPROVED,
    )
    Request.objects.create(
        lab=lab, item_name="Nobody ordered yet", requested_by=member, status=Status.APPROVED
    )
    Request.objects.create(
        lab=lab,
        item_name="Someone else handles",
        requested_by=member,
        assigned_to=other_coord,
        status=Status.APPROVED,
    )
    client.force_login(coord)
    resp = client.get(reverse("home"))
    assert b"Requests to order" in resp.content
    assert b"Assigned to me" in resp.content
    assert b"Nobody ordered yet" in resp.content
    assert b"Someone else handles" not in resp.content
    assert b"Mark ordered" in resp.content


@pytest.mark.django_db
def test_deliveries_widget_scoped_to_my_involvement(lab):
    from labbutler import dashboard

    manager = _user(lab, "m@x.de", ["Lab manager"])  # has check_in via "*"
    other = _user(lab, "o@x.de", ["Member"])
    Request.objects.create(
        lab=lab, item_name="I requested", requested_by=manager, status=Status.ORDERED
    )
    Request.objects.create(
        lab=lab,
        item_name="I order",
        requested_by=other,
        assigned_to=manager,
        status=Status.DELIVERED,
    )
    Request.objects.create(
        lab=lab, item_name="Someone else", requested_by=other, status=Status.ORDERED
    )
    Request.objects.create(  # right person, wrong status
        lab=lab, item_name="Not yet ordered", requested_by=manager, status=Status.APPROVED
    )

    widgets = {w.key: w for w in dashboard.build(manager, lab)}
    deliveries = widgets["deliveries"]
    assert deliveries.title == "Expecting deliveries"
    assert {r.item_name for r in deliveries.items} == {"I requested", "I order"}
    assert deliveries.total == 2
    assert deliveries.view_all_url.endswith("?mine=1&status=ordered&status=delivered")


@pytest.mark.django_db
def test_deliveries_widget_caps_items_at_ten(lab):
    from labbutler import dashboard

    manager = _user(lab, "m@x.de", ["Lab manager"])
    for i in range(12):
        Request.objects.create(
            lab=lab, item_name=f"Delivery {i:02d}", requested_by=manager, status=Status.ORDERED
        )

    deliveries = {w.key: w for w in dashboard.build(manager, lab)}["deliveries"]
    assert len(deliveries.items) == 10
    assert deliveries.total == 12


@pytest.mark.django_db
def test_request_widgets_list_newest_first(lab):
    from labbutler import dashboard

    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    for i in range(8):  # more than the widget limit of 6
        Request.objects.create(
            lab=lab, item_name=f"Approval {i}", requested_by=member, status=Status.REQUESTED
        )
        Request.objects.create(
            lab=lab, item_name=f"Order {i}", requested_by=member, status=Status.APPROVED
        )

    widgets = {w.key: w for w in dashboard.build(manager, lab)}
    # Newest first, so a full queue doesn't pin the same oldest rows forever (#7).
    assert [r.item_name for r in widgets["approvals"].items] == [
        f"Approval {i}" for i in range(7, 1, -1)
    ]
    assert [r.item_name for r in widgets["to_order"].items] == [
        f"Order {i}" for i in range(7, 1, -1)
    ]


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
def test_order_widget_gated_on_place_order_permission(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    Request.objects.create(
        lab=lab, item_name="Waiting", requested_by=member, status=Status.APPROVED
    )
    # Anyone holding place_order can order — the widget must not require the literal
    # "Purchase coordinator" role (#10): a manager has place_order via "*".
    client.force_login(_user(lab, "m@x.de", ["Lab manager"]))
    resp = client.get(reverse("home"))
    assert b"Requests to order" in resp.content

    client.force_login(member)  # no place_order -> no widget
    resp = client.get(reverse("home"))
    assert b"Requests to order" not in resp.content


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


@pytest.mark.django_db
def test_my_requests_in_progress_scope(lab):
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
        item_name="Forwarded",
        requested_by=member,
        status=Status.APPROVED,
        assigned_to=coord,
    )
    Request.objects.create(lab=lab, item_name="Ordered", requested_by=member, status=Status.ORDERED)
    Request.objects.create(
        lab=lab, item_name="Delivered", requested_by=member, status=Status.DELIVERED
    )
    Request.objects.create(lab=lab, item_name="Done", requested_by=member, status=Status.CHECKED_IN)

    widgets = {w.key: w for w in dashboard.build(member, lab)}
    tracking = widgets["tracking"]
    assert tracking.title == "My requests in progress"
    # Being handled elsewhere: forwarded / ordered / delivered — not pending, not finished.
    assert {r.item_name for r in tracking.items} == {"Forwarded", "Ordered", "Delivered"}
