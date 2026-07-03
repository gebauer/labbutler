"""Procurement state-machine tests: transitions, permissions, and check-in side effects."""

from decimal import Decimal

import pytest

from apps.procurement import services
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

    from apps.inventory.models import Location

    fridge = Location.objects.create(lab=lab, name="Fridge 2")
    services.receive(req, actor=member, create_item=True, location=fridge)
    req.refresh_from_db()
    assert req.status == Status.CHECKED_IN
    assert req.created_item is not None
    assert req.created_item.name == "Pipette tips"
    assert req.created_item.owner == member
    assert req.created_item.location == fridge
    assert req.created_item.human_id.startswith("LB-")


@pytest.fixture
def _tmp_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")


def _attach_pdf(lab, req, by):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.attachments.models import Attachment

    return Attachment.objects.create(
        lab=lab,
        uploaded_by=by,
        target=req,
        file=SimpleUploadedFile("po.pdf", b"po body"),
        original_name="po.pdf",
        size=7,
    )


@pytest.mark.django_db
def test_receive_does_not_carry_attachments_by_default(lab, _tmp_media):
    from apps.attachments.models import Attachment

    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, status=Status.ORDERED)
    _attach_pdf(lab, req, member)

    services.receive(req, actor=member, create_item=True)
    assert not Attachment.for_object(req.created_item).exists()
    assert Attachment.for_object(req).count() == 1  # stays on the request


@pytest.mark.django_db
def test_receive_carries_attachments_when_asked(lab, _tmp_media):
    from apps.attachments.models import Attachment

    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, status=Status.ORDERED)
    _attach_pdf(lab, req, member)

    services.receive(req, actor=member, create_item=True, carry_attachments=True)
    copy = Attachment.for_object(req.created_item).get()
    assert copy.original_name == "po.pdf"
    assert Attachment.for_object(req).count() == 1  # copied, not moved


@pytest.mark.django_db
def test_receive_carries_hazard_data_onto_the_item(lab):
    from apps.inventory.models import HazardStatement

    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, status=Status.ORDERED, signal_word="danger", storage_class="8A")
    req.hazards.set(HazardStatement.objects.filter(code__in=["H225", "P210"]))

    services.receive(req, actor=member, create_item=True)
    item = req.created_item
    assert item.signal_word == "danger"
    assert item.storage_class == "8A"
    assert sorted(h.code for h in item.hazards.all()) == ["H225", "P210"]


@pytest.mark.django_db
def test_receive_without_item_marks_received(lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, status=Status.ORDERED)
    services.receive(req, actor=manager, create_item=False)
    req.refresh_from_db()
    assert req.status == Status.RECEIVED
    assert req.created_item is None


@pytest.mark.django_db
def test_received_is_terminal(lab):
    """Issue #5: a request received without an item is done — no re-receive, no cancel."""
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, status=Status.ORDERED)
    services.receive(req, actor=manager, create_item=False)

    assert not services.can_receive(manager, req)
    with pytest.raises(TransitionError):
        services.receive(req, actor=manager, create_item=True)
    assert not may_perform(manager, req, TRANSITIONS["cancel"])
    assert available_transitions(manager, req) == []


@pytest.mark.django_db
def test_delivered_stays_receivable(lab):
    """Imported orders land in Delivered (arrived, not yet checked in) and must remain
    receivable — only the new Received status is terminal."""
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, status=Status.DELIVERED)
    assert services.can_receive(manager, req)


@pytest.mark.django_db
def test_receive_rejects_non_ordered(lab):
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)  # still 'requested'
    with pytest.raises(TransitionError):
        services.receive(req, actor=member, create_item=True)


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


@pytest.mark.django_db
def test_purchase_coordinators_are_place_order_holders(lab):
    _user(lab, "m@x.de", ["Lab manager"])  # place_order via "*"
    _user(lab, "c@x.de", ["Purchase coordinator"])
    _user(lab, "u@x.de", ["Member"])  # no place_order
    emails = set(services.purchase_coordinators(lab).values_list("email", flat=True))
    assert {"m@x.de", "c@x.de"} <= emails
    assert "u@x.de" not in emails


@pytest.mark.django_db
def test_can_forward_only_when_approved_and_involved(lab):
    member = _user(lab, "u@x.de", ["Member"])
    stranger = _user(lab, "s@x.de", ["Member"])
    req = _request(lab, member)  # requested
    assert services.can_forward(member, req) is False  # not approved yet
    req.status = Status.APPROVED
    req.save()
    assert services.can_forward(member, req) is True  # requester of an approved request
    assert services.can_forward(stranger, req) is False  # uninvolved member


@pytest.mark.django_db
def test_forward_assigns_and_audits(lab):
    from apps.audit.models import AuditEntry

    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    coord = _user(lab, "c@x.de", ["Purchase coordinator"])
    req = _request(lab, member, status=Status.APPROVED)
    services.forward(req, actor=manager, assignee=coord)
    req.refresh_from_db()
    assert req.assigned_to == coord
    assert AuditEntry.objects.filter(
        action="procurement.request_forwarded", target_id=str(req.pk)
    ).exists()
