"""Central-purchasing notification tests: the signature request and the forward-ready
ZK email (the one mail that carries the signed PDF, addressed to the request's manager)."""

from decimal import Decimal

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEntry
from apps.notifications import emails
from apps.notifications.tasks import notify_po_signature_needed, send_zk_forward_email
from apps.procurement import services
from apps.procurement.models import Request
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab

Status = Request.Status


@pytest.fixture
def lab(db):
    return create_lab(name="Mail Lab", item_id_prefix="LB")


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")


def _user(lab, email: str, roles: list[str], friendly_name: str = "") -> User:
    user = User.objects.create_user(
        username="", email=email, password="pw", friendly_name=friendly_name
    )
    add_member(user=user, lab=lab, role_names=roles)
    return user


def _pdf(name: str = "form.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")


def _central_request(lab, by, status=Status.APPROVED) -> Request:
    req = Request.objects.create(
        lab=lab,
        item_name="Zentrifuge",
        requested_by=by,
        unit_price=Decimal("1500.00"),
        procurement_route=Request.Route.CENTRAL,
        status=status,
    )
    req.recalculate_totals()
    req.save()
    return req


@pytest.mark.django_db
def test_build_zk_forward_body_is_pure_and_signs_with_the_recipient(lab):
    member = _user(lab, "ada@x.de", ["Member"], friendly_name="Ada Lovelace")
    req = _central_request(lab, member)

    content = emails.build_zk_forward(req, member)

    assert content.subject == "Beschaffungsantrag Zentrifuge"
    assert "[LabButler]" not in content.subject  # gets forwarded verbatim
    assert content.body.startswith("Lieber Zentraleinkauf,")
    assert content.body.rstrip().endswith("Ada Lovelace")
    assert "LabButler" not in content.body  # no internal instructions or footer
    assert content.html is None


@pytest.mark.django_db
def test_send_zk_forward_email_attaches_the_signed_pdf_and_audits(lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _central_request(lab, member)
    services.create_po(req, actor=member, upload=_pdf())
    services.upload_signed_po(req, actor=manager, upload=_pdf("signed.pdf"))
    mail.outbox.clear()

    assert send_zk_forward_email(req.pk) == 1

    message = mail.outbox[0]
    assert message.to == [member.email]  # the request's manager, not a role
    assert message.subject == "Beschaffungsantrag Zentrifuge"
    filename, data, mimetype = message.attachments[0]
    assert filename == f"Beschaffungsantrag_Request_{req.pk}_signiert.pdf"
    assert data == b"%PDF-1.4 test"
    assert mimetype == "application/pdf"
    entry = AuditEntry.objects.get(
        lab=lab, action="procurement.po_forward_email_sent", target_id=str(req.pk)
    )
    assert entry.changes["recipient"] == member.email


@pytest.mark.django_db
def test_send_zk_forward_email_goes_to_the_assignee_when_forwarded(lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    req = _central_request(lab, member)
    req.assigned_to = coordinator
    req.save()
    services.create_po(req, actor=coordinator, upload=_pdf())
    services.upload_signed_po(req, actor=manager, upload=_pdf())
    mail.outbox.clear()

    send_zk_forward_email(req.pk)

    assert mail.outbox[0].to == [coordinator.email]


@pytest.mark.django_db
def test_send_zk_forward_email_requires_a_signed_po(lab):
    member = _user(lab, "u@x.de", ["Member"])
    req = _central_request(lab, member)
    services.create_po(req, actor=member, upload=_pdf())
    mail.outbox.clear()

    assert send_zk_forward_email(req.pk) == 0
    assert not mail.outbox


@pytest.mark.django_db
def test_notify_po_signature_needed_targets_sign_po_holders(lab):
    _user(lab, "m@x.de", ["Lab manager"])  # holds sign_po by default
    member = _user(lab, "u@x.de", ["Member"])
    req = _central_request(lab, member)
    services.create_po(req, actor=member, upload=_pdf())
    mail.outbox.clear()

    assert notify_po_signature_needed(req.pk) == 1

    message = mail.outbox[0]
    assert message.to == ["m@x.de"]
    assert "Signature needed" in message.subject


@pytest.mark.django_db
def test_notify_po_signature_needed_only_while_po_created(lab):
    _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _central_request(lab, member)  # still Approved
    mail.outbox.clear()

    assert notify_po_signature_needed(req.pk) == 0
    assert not mail.outbox
