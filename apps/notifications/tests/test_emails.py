"""Pure email-builder tests — no DB, no SMTP, just content."""

from datetime import date
from decimal import Decimal

from apps.inventory.models import Item
from apps.notifications.emails import build_expiry_digest, build_status_change
from apps.procurement.models import Request

Status = Request.Status


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
