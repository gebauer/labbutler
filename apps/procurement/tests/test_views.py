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
def test_full_workflow_checkin_creates_item_and_redirects(client, lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = Request.objects.create(
        lab=lab, item_name="Tips", requested_by=member, unit_price=Decimal("5.00")
    )
    client.force_login(manager)
    client.post(reverse("procurement:request_action", args=[req.pk, "approve"]))
    client.post(
        reverse("procurement:request_action", args=[req.pk, "order"]), {"po_number": "PO-9"}
    )
    resp = client.post(reverse("procurement:request_action", args=[req.pk, "check_in"]))

    assert resp.status_code == 302
    req.refresh_from_db()
    assert req.status == Status.CHECKED_IN
    assert req.po_number == "PO-9"
    assert Item.objects.filter(lab=lab, pk=req.created_item_id).exists()
    assert reverse("inventory:item_detail", args=[req.created_item_id]) in resp["Location"]


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
