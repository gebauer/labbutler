"""Pure email-builder tests — no DB, no SMTP, just content."""

from datetime import date
from decimal import Decimal

from apps.inventory.models import Item
from apps.notifications.emails import (
    build_approval_needed,
    build_assignment,
    build_expiry_digest,
    build_status_change,
    build_welcome,
)
from apps.procurement.models import Request, Vendor
from apps.tenancy.models import User

Status = Request.Status


def _request(**overrides) -> Request:
    """An unsaved request wired to unsaved-but-pk'd related objects (no DB needed)."""
    fields = {
        "pk": 6,
        "item_name": "Whole-plasmid sequencing",
        "total": Decimal("89.25"),
        "currency": "EUR",
        "requested_by": User(pk=1, email="ada@x.de", friendly_name="Ada Lovelace"),
        "vendor": Vendor(pk=2, name="Eurofins"),
    }
    fields.update(overrides)
    return Request(**fields)


def test_status_change_subject_and_body():
    req = Request(item_name="Pipette tips", total=Decimal("249.90"), currency="EUR")
    content = build_status_change(req, Status.REQUESTED, Status.APPROVED)
    assert "Pipette tips" in content.subject
    assert "Approved" in content.subject
    assert "Requested → Approved" in content.body
    assert "249.90 EUR" in content.body


def test_status_change_appends_link_only_with_base_url():
    req = Request(pk=5, item_name="X")
    without = build_status_change(req, Status.REQUESTED, Status.APPROVED)
    assert "http" not in without.body
    withlink = build_status_change(
        req, Status.REQUESTED, Status.APPROVED, base_url="https://lab.example.org/"
    )
    assert "https://lab.example.org/requests/5/" in withlink.body


def test_welcome_greets_member_and_carries_set_password_link():
    from apps.tenancy.models import User

    user = User(email="new@x.de", friendly_name="Ada Lovelace")

    class FakeLab:
        name = "AG Baumann"

    url = "https://lab.example.org/accounts/reset/MQ/set-token/"
    content = build_welcome(user, FakeLab(), url)
    assert content.subject == "[LabButler] Welcome to AG Baumann"
    assert "Ada Lovelace" in content.body
    assert "AG Baumann" in content.body
    assert url in content.body


def test_status_change_reports_auto_forward_only_on_approval():
    coordinator = User(pk=4, email="marie@x.de", friendly_name="Marie Curie")
    req = _request(assigned_to=coordinator)
    approved = build_status_change(req, Status.REQUESTED, Status.APPROVED)
    assert "Forwarded to: Marie Curie (marie@x.de) to order, as you requested." in approved.body
    ordered = build_status_change(req, Status.APPROVED, Status.ORDERED)
    assert "as you requested" not in ordered.body


def test_approval_needed_names_requester_price_and_vendor():
    content = build_approval_needed(_request(), base_url="https://lab.example.org")
    assert content.subject == "[LabButler] Approval needed: “Whole-plasmid sequencing”"
    assert "Ada Lovelace (ada@x.de) asks to order:" in content.body
    assert "89.25 EUR" in content.body
    assert "Eurofins" in content.body
    assert "https://lab.example.org/requests/6/" in content.body
    assert content.urgent is False
    assert "URGENT" not in content.body


def test_approval_needed_html_carries_details_and_action_button():
    content = build_approval_needed(_request(), base_url="https://lab.example.org")
    assert 'href="https://lab.example.org/requests/6/"' in content.html
    assert "See request details" in content.html
    assert "Ada Lovelace (ada@x.de)" in content.html
    assert "89.25 EUR" in content.html


def test_urgent_approval_is_flagged_in_subject_body_and_html():
    content = build_approval_needed(_request(is_urgent=True))
    assert content.urgent is True
    assert content.subject.startswith("[LabButler] URGENT — Approval needed:")
    assert content.body.startswith("URGENT — the requester needs a decision")
    assert "URGENT" in content.html


def test_assignment_names_forwarder_and_requester():
    forwarder = User(pk=3, email="marie@x.de", friendly_name="Marie Curie")
    content = build_assignment(
        _request(), forwarded_by=forwarder, base_url="https://lab.example.org"
    )
    assert content.subject == "[LabButler] Please order “Whole-plasmid sequencing”"
    assert "Marie Curie (marie@x.de) has forwarded an approved request" in content.body
    assert "Requested by:" in content.body and "Ada Lovelace (ada@x.de)" in content.body
    assert "89.25 EUR" in content.body
    assert 'href="https://lab.example.org/requests/6/"' in content.html


def test_assignment_without_forwarder_keeps_generic_intro():
    content = build_assignment(_request())
    assert "An approved request has been forwarded to you to order:" in content.body


def test_urgent_assignment_is_flagged_in_subject_and_body():
    forwarder = User(pk=3, email="marie@x.de")
    content = build_assignment(_request(is_urgent=True), forwarded_by=forwarder)
    assert content.urgent is True
    assert content.subject.startswith("[LabButler] URGENT — Please order")
    assert "URGENT — this needs to be ordered as soon as possible." in content.body
    # A forwarder without a friendly name is identified by email alone.
    assert "marie@x.de has forwarded" in content.body


def test_expiry_digest_lists_items_and_counts():
    today = date(2026, 7, 1)
    expired = [Item(human_id="LB-1", name="Old Tris", expiration_date=date(2026, 6, 1))]
    expiring = [Item(human_id="LB-2", name="Soon Agar", expiration_date=date(2026, 7, 15))]

    class FakeLab:
        name = "AG Baumann"

    content = build_expiry_digest(FakeLab(), expired, expiring, today, days_ahead=30)
    assert "1 expired" in content.subject
    assert "1 expiring within 30 days" in content.subject
    assert "LB-1" in content.body and "Old Tris" in content.body
    assert "LB-2" in content.body and "Soon Agar" in content.body
