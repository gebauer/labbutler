"""Procurement state-machine tests: transitions, permissions, and check-in side effects."""

from decimal import Decimal

import pytest

from apps.procurement.models import Request
from apps.procurement.services import (
    TRANSITIONS,
    TransitionError,
    available_transitions,
    may_perform,
    perform_transition,
)
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


def _request(lab, by, **kwargs) -> Request:
    return Request.objects.create(lab=lab, item_name="Pipette tips", requested_by=by, **kwargs)


@pytest.mark.django_db
def test_happy_path_to_checked_in_creates_linked_item(lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, unit_price=Decimal("10.00"), currency="EUR")

    perform_transition(req, "approve", actor=manager)
    assert req.status == Status.APPROVED
    assert req.approver == manager

    perform_transition(req, "order", actor=manager, po_number="PO-1")
    assert req.status == Status.ORDERED
    assert req.po_number == "PO-1"

    perform_transition(req, "check_in", actor=member)
    req.refresh_from_db()
    assert req.status == Status.CHECKED_IN
    assert req.created_item is not None
    assert req.created_item.name == "Pipette tips"
    assert req.created_item.owner == member
    assert req.created_item.human_id.startswith("LB-")


@pytest.mark.django_db
def test_invalid_transition_raises(lab):
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    with pytest.raises(TransitionError):
        perform_transition(req, "order", actor=member)  # can't order a still-'requested'
    req.refresh_from_db()
    assert req.status == Status.REQUESTED


@pytest.mark.django_db
def test_may_perform_enforces_permission(lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])  # no approve_request
    req = _request(lab, member)
    assert may_perform(manager, req, TRANSITIONS["approve"]) is True
    assert may_perform(member, req, TRANSITIONS["approve"]) is False


@pytest.mark.django_db
def test_requester_may_cancel_own_but_others_may_not(lab):
    member = _user(lab, "u@x.de", ["Member"])
    stranger = _user(lab, "s@x.de", ["Member"])
    req = _request(lab, member)
    assert may_perform(member, req, TRANSITIONS["cancel"]) is True
    assert may_perform(stranger, req, TRANSITIONS["cancel"]) is False


@pytest.mark.django_db
def test_available_transitions_for_requested(lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    assert {t.action for t in available_transitions(manager, req)} == {
        "approve",
        "reject",
        "cancel",
    }
    assert {t.action for t in available_transitions(member, req)} == {"cancel"}
