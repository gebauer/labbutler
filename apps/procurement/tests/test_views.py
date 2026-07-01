"""Procurement view tests: create/list/detail, workflow actions, gating, and scoping."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.inventory.models import Item
from apps.procurement.models import Request
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab

Status = Request.Status


@pytest.fixture
def lab(db):
    return create_lab(name="Proc Lab", item_id_prefix="LB")


def _user(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


@pytest.mark.django_db
def test_create_request_computes_totals(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    client.force_login(member)
    resp = client.post(
        reverse("procurement:request_create"),
        {
            "item_name": "Tips",
            "currency": "EUR",
            "unit_price": "100.00",
            "pack_count": "2",
            "shipping_cost": "10.00",
            "tags": [],
        },
    )
    assert resp.status_code == 302
    req = Request.objects.get(item_name="Tips")
    assert req.requested_by == member
    assert req.total == Decimal("249.90")  # (100*2 + 10) * 1.19


@pytest.mark.django_db
def test_list_is_scoped_to_lab(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    other = create_lab(name="Other", item_id_prefix="OT")
    Request.objects.create(lab=lab, item_name="Mine", requested_by=member)
    Request.objects.create(lab=other, item_name="NotMine")
    client.force_login(member)
    resp = client.get(reverse("procurement:request_list"))
    assert b"Mine" in resp.content
    assert b"NotMine" not in resp.content


@pytest.mark.django_db
def test_action_forbidden_without_permission(client, lab):
    member = _user(lab, "u@x.de", ["Member"])  # no approve_request
    req = Request.objects.create(lab=lab, item_name="Tips", requested_by=member)
    client.force_login(member)
    resp = client.post(reverse("procurement:request_action", args=[req.pk, "approve"]))
    assert resp.status_code == 403
    req.refresh_from_db()
    assert req.status == Status.REQUESTED


@pytest.mark.django_db
def test_full_workflow_receive_checks_in_and_labels(client, lab):
    from apps.inventory.models import Location

    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    fridge = Location.objects.create(lab=lab, name="Fridge 2")
    req = Request.objects.create(
        lab=lab, item_name="Tips", requested_by=member, unit_price=Decimal("5.00")
    )
    client.force_login(manager)
    client.post(reverse("procurement:request_action", args=[req.pk, "approve"]))
    client.post(
        reverse("procurement:request_action", args=[req.pk, "order"]), {"po_number": "PO-9"}
    )
    resp = client.post(
        reverse("procurement:request_receive", args=[req.pk]),
        {"outcome": "check_in", "location": fridge.pk},
    )

    assert resp.status_code == 302
    req.refresh_from_db()
    assert req.status == Status.CHECKED_IN
    item = Item.objects.get(lab=lab, pk=req.created_item_id)
    assert item.location == fridge
    # Check-in sends you to the print-label page.
    assert reverse("inventory:item_label", args=[item.pk]) in resp["Location"]


@pytest.mark.django_db
def test_receive_without_location_needs_confirmation(client, lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    req = Request.objects.create(
        lab=lab, item_name="Tips", requested_by=manager, status=Status.ORDERED
    )
    client.force_login(manager)
    # First attempt with no location re-renders the dialog with a confirmation.
    first = client.post(
        reverse("procurement:request_receive", args=[req.pk]), {"outcome": "check_in"}
    )
    assert first.status_code == 200
    assert b"confirm_no_location" in first.content
    req.refresh_from_db()
    assert req.status == Status.ORDERED  # nothing happened yet

    second = client.post(
        reverse("procurement:request_receive", args=[req.pk]),
        {"outcome": "check_in", "confirm_no_location": "1"},
    )
    assert second.status_code == 302
    req.refresh_from_db()
    assert req.status == Status.CHECKED_IN
    assert req.created_item.location is None


@pytest.mark.django_db
def test_receive_without_item_marks_delivered(client, lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    req = Request.objects.create(
        lab=lab, item_name="Site licence", requested_by=manager, status=Status.ORDERED
    )
    client.force_login(manager)
    resp = client.post(
        reverse("procurement:request_receive", args=[req.pk]), {"outcome": "no_item"}
    )
    assert resp.status_code == 302
    req.refresh_from_db()
    assert req.status == Status.DELIVERED
    assert req.created_item is None
    assert not Item.objects.filter(lab=lab).exists()


@pytest.mark.django_db
def test_receive_forbidden_without_check_in_permission(client, lab):
    viewer = _user(lab, "v@x.de", ["Viewer"])  # no check_in
    req = Request.objects.create(
        lab=lab, item_name="Tips", requested_by=viewer, status=Status.ORDERED
    )
    client.force_login(viewer)
    assert client.get(reverse("procurement:request_receive", args=[req.pk])).status_code == 403


@pytest.mark.django_db
def test_edit_blocked_after_approval(client, lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    req = Request.objects.create(
        lab=lab, item_name="Tips", requested_by=manager, status=Status.APPROVED
    )
    client.force_login(manager)
    resp = client.get(reverse("procurement:request_edit", args=[req.pk]))
    assert resp.status_code == 302  # bounced back to detail with a message


@pytest.mark.django_db
def test_list_requires_view_requests_permission(client, lab):
    nobody = User.objects.create_user(username="", email="n@x.de", password="pw")
    add_member(user=nobody, lab=lab)  # member of the lab but no roles
    client.force_login(nobody)
    resp = client.get(reverse("procurement:request_list"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_filter_by_multiple_statuses(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    Request.objects.create(lab=lab, item_name="ReqA", requested_by=member, status=Status.REQUESTED)
    Request.objects.create(lab=lab, item_name="OrdB", requested_by=member, status=Status.ORDERED)
    Request.objects.create(lab=lab, item_name="AppC", requested_by=member, status=Status.APPROVED)
    client.force_login(member)
    resp = client.get(reverse("procurement:request_list"), {"status": ["requested", "ordered"]})
    assert b"ReqA" in resp.content
    assert b"OrdB" in resp.content
    assert b"AppC" not in resp.content


@pytest.mark.django_db
def test_request_search_and_vendor_filter(client, lab):
    from apps.procurement.models import Vendor

    member = _user(lab, "u@x.de", ["Member"])
    sigma = Vendor.objects.create(lab=lab, name="Sigma")
    Request.objects.create(lab=lab, item_name="Tips box", requested_by=member, vendor=sigma)
    Request.objects.create(lab=lab, item_name="Gloves", requested_by=member)
    client.force_login(member)
    by_q = client.get(reverse("procurement:request_list"), {"q": "tips"})
    assert b"Tips box" in by_q.content and b"Gloves" not in by_q.content
    by_vendor = client.get(reverse("procurement:request_list"), {"vendor": sigma.pk})
    assert b"Tips box" in by_vendor.content and b"Gloves" not in by_vendor.content


@pytest.mark.django_db
def test_request_infinite_scroll_chunk(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    for i in range(26):
        Request.objects.create(lab=lab, item_name=f"Req {i:02d}", requested_by=member)
    client.force_login(member)
    first = client.get(reverse("procurement:request_list"))
    assert b'hx-trigger="revealed"' in first.content
    chunk = client.get(reverse("procurement:request_list"), {"partial": "chunk", "page": 2})
    assert chunk.status_code == 200
    assert b'id="request-results"' not in chunk.content
    assert b"/requests/" in chunk.content


@pytest.mark.django_db
def test_request_detail_shows_history(client, lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = Request.objects.create(lab=lab, item_name="Tips", requested_by=member)
    client.force_login(manager)
    client.post(reverse("procurement:request_action", args=[req.pk, "approve"]))
    resp = client.get(reverse("procurement:request_detail", args=[req.pk]))
    assert b"History" in resp.content
    assert b"request_approve" in resp.content
