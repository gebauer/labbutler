"""Admin "danger zone": deleting a lab's whole inventory or all its requests."""

from pathlib import Path

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.attachments.models import Attachment
from apps.audit.models import AuditEntry
from apps.inventory.models import Item, Location, Tag
from apps.procurement.models import PurchaseOrder, Request, Vendor
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


@pytest.fixture
def other_lab(db):
    return create_lab(name="AG Other", item_id_prefix="OTH")


@pytest.fixture
def manager(lab):
    return _member(lab, "boss@x.de", ["Lab manager"])


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")


def _member(lab, email, roles) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


def _item(lab, name="Ethanol", **kwargs) -> Item:
    return Item.objects.create(lab=lab, human_id=lab.allocate_item_id(), name=name, **kwargs)


def _request(lab, user, **kwargs) -> Request:
    return Request.objects.create(lab=lab, item_name="Tips", requested_by=user, **kwargs)


def _pdf(name="form.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4", content_type="application/pdf")


@pytest.mark.django_db
def test_reset_pages_require_manage_lab(client, lab):
    client.force_login(_member(lab, "member@x.de", ["Member"]))
    for name in ("manage:reset_inventory", "manage:reset_requests"):
        assert client.get(reverse(name)).status_code == 403
        assert client.post(reverse(name), {"confirm_name": lab.name}).status_code == 403


@pytest.mark.django_db
def test_admin_index_links_to_both_resets(client, lab, manager):
    client.force_login(manager)
    content = client.get(reverse("manage:index")).content.decode()
    assert reverse("manage:reset_inventory") in content
    assert reverse("manage:reset_requests") in content


@pytest.mark.django_db
def test_confirm_page_shows_what_will_be_deleted(client, lab, manager):
    _item(lab, location=Location.objects.create(lab=lab, name="Fridge"))
    _item(lab, name="Acetone")
    client.force_login(manager)
    resp = client.get(reverse("manage:reset_inventory"))
    assert resp.status_code == 200
    assert b"<strong>2</strong> items" in resp.content
    assert b"<strong>1</strong> location" in resp.content
    assert Item.objects.filter(lab=lab).count() == 2  # GET deletes nothing


@pytest.mark.django_db
def test_wrong_name_deletes_nothing(client, lab, manager):
    _item(lab)
    _request(lab, manager)
    client.force_login(manager)
    for name in ("manage:reset_inventory", "manage:reset_requests"):
        resp = client.post(reverse(name), {"confirm_name": "AG Baumannn"})
        assert resp.status_code == 400
        assert b"doesn&#x27;t match" in resp.content
    assert Item.objects.filter(lab=lab).count() == 1
    assert Request.objects.filter(lab=lab).count() == 1
    assert (
        not AuditEntry.objects.filter(action__startswith="lab.")
        .filter(action__endswith="_deleted")
        .exists()
    )


@pytest.mark.django_db
def test_delete_inventory_removes_lab_items_locations_and_unused_tags(
    client, lab, other_lab, manager, django_capture_on_commit_callbacks
):
    fridge = Location.objects.create(lab=lab, name="Fridge")
    Location.objects.create(lab=lab, name="Shelf", parent=fridge)
    solvent = Tag.objects.create(lab=lab, name="solvent")
    ordered = Tag.objects.create(lab=lab, name="ordered")
    item = _item(lab, location=fridge)
    item.tags.add(solvent, ordered)
    request_obj = _request(lab, manager, source_item=item)
    request_obj.tags.add(ordered)
    attachment = Attachment.objects.create(
        lab=lab,
        content_type=ContentType.objects.get_for_model(Item),
        object_id=item.pk,
        file=_pdf("sds.pdf"),
        original_name="sds.pdf",
        size=8,
    )
    stored = Path(attachment.file.path)
    other_item = _item(other_lab, name="Not mine")
    client.force_login(manager)

    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(reverse("manage:reset_inventory"), {"confirm_name": " ag  baumann "})

    assert resp.status_code == 302
    assert resp["Location"] == reverse("inventory:item_list")
    assert not Item.objects.filter(lab=lab).exists()
    assert not Location.objects.filter(lab=lab).exists()
    assert list(Tag.objects.filter(lab=lab)) == [ordered]  # still on the request
    assert not Attachment.objects.filter(pk=attachment.pk).exists()
    request_obj.refresh_from_db()
    assert request_obj.source_item is None  # request kept, link dropped
    assert Item.objects.filter(pk=other_item.pk).exists()  # other labs untouched
    entry = AuditEntry.objects.get(action="lab.inventory_deleted")
    assert entry.lab == lab and entry.actor == manager
    assert entry.changes == {"items": 1, "locations": 2, "tags": 1}
    assert not stored.exists()


@pytest.mark.django_db
def test_delete_requests_removes_requests_and_po_files(
    client, lab, other_lab, manager, django_capture_on_commit_callbacks
):
    item = _item(lab)
    request_obj = _request(lab, manager, created_item=item)
    po = PurchaseOrder.objects.create(
        request=request_obj, po_snapshot_net=10, unsigned_pdf=_pdf(), signed_pdf=_pdf("s.pdf")
    )
    files = [Path(po.unsigned_pdf.path), Path(po.signed_pdf.path)]
    vendor = Vendor.objects.create(lab=lab, name="Carl Roth")
    _request(lab, manager, vendor=vendor)
    other_member = _member(other_lab, "other@x.de", ["Lab manager"])
    other_request = _request(other_lab, other_member)
    client.force_login(manager)

    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(reverse("manage:reset_requests"), {"confirm_name": "AG Baumann"})

    assert resp.status_code == 302
    assert resp["Location"] == reverse("procurement:request_list")
    assert not Request.objects.filter(lab=lab).exists()
    assert not PurchaseOrder.objects.exists()
    assert all(not path.exists() for path in files)
    assert Item.objects.filter(pk=item.pk).exists()  # received items stay in inventory
    assert Vendor.objects.filter(pk=vendor.pk).exists()
    assert Request.objects.filter(pk=other_request.pk).exists()
    entry = AuditEntry.objects.get(action="lab.requests_deleted")
    assert entry.changes == {"requests": 2}


@pytest.mark.django_db
def test_success_message_reports_counts(client, lab, manager):
    _item(lab)
    client.force_login(manager)
    resp = client.post(
        reverse("manage:reset_inventory"), {"confirm_name": "AG Baumann"}, follow=True
    )
    assert b"Deleted 1 item, 0 locations, 0 tags." in resp.content
