"""Attachment upload/download/delete: gating, tenant scoping, validation, file cleanup."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.attachments.models import Attachment
from apps.inventory.models import Item
from apps.procurement.models import Request
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


def _user(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


def _item(lab, name: str = "Ethanol") -> Item:
    return Item.objects.create(lab=lab, human_id=lab.allocate_item_id(), name=name)


def _pdf(name: str = "sds.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"%PDF-1.4 fake", content_type="application/pdf")


@pytest.mark.django_db
def test_upload_to_item_and_shows_on_detail(client, lab):
    member = _user(lab, "m@x.de", ["Member"])
    item = _item(lab)
    client.force_login(member)
    resp = client.post(reverse("attachments:add", args=["item", item.pk]), {"file": _pdf()})
    assert resp.status_code == 302 and resp["Location"].endswith("#attachments")

    attachment = Attachment.for_object(item).get()
    assert attachment.original_name == "sds.pdf"
    assert attachment.uploaded_by == member and attachment.lab == lab
    assert attachment.size > 0
    # Stored under a random name, never the user-supplied one.
    assert "sds" not in attachment.file.name

    detail = client.get(reverse("inventory:item_detail", args=[item.pk]))
    assert b"sds.pdf" in detail.content


@pytest.mark.django_db
def test_viewer_cannot_upload_but_can_download(client, lab):
    member = _user(lab, "m@x.de", ["Member"])
    viewer = _user(lab, "v@x.de", ["Viewer"])
    item = _item(lab)
    client.force_login(member)
    client.post(reverse("attachments:add", args=["item", item.pk]), {"file": _pdf()})
    attachment = Attachment.for_object(item).get()

    client.force_login(viewer)
    resp = client.post(reverse("attachments:add", args=["item", item.pk]), {"file": _pdf()})
    assert resp.status_code == 403

    download = client.get(reverse("attachments:download", args=[attachment.pk]))
    assert download.status_code == 200
    assert download["Content-Disposition"].endswith('filename="sds.pdf"')
    assert b"".join(download.streaming_content) == b"%PDF-1.4 fake"

    delete = client.post(reverse("attachments:delete", args=[attachment.pk]))
    assert delete.status_code == 403


@pytest.mark.django_db
def test_other_lab_cannot_reach_attachment(client, lab):
    member = _user(lab, "m@x.de", ["Member"])
    item = _item(lab)
    client.force_login(member)
    client.post(reverse("attachments:add", args=["item", item.pk]), {"file": _pdf()})
    attachment = Attachment.for_object(item).get()

    other = create_lab(name="Other", item_id_prefix="OT")
    outsider = _user(other, "o@x.de", ["Lab manager"])
    client.force_login(outsider)
    assert client.get(reverse("attachments:download", args=[attachment.pk])).status_code == 404
    assert client.post(reverse("attachments:delete", args=[attachment.pk])).status_code == 404


@pytest.mark.django_db
def test_disallowed_extension_is_rejected(client, lab):
    member = _user(lab, "m@x.de", ["Member"])
    item = _item(lab)
    client.force_login(member)
    exe = SimpleUploadedFile("run.exe", b"MZ", content_type="application/octet-stream")
    resp = client.post(reverse("attachments:add", args=["item", item.pk]), {"file": exe})
    assert resp.status_code == 302  # redirected back with an error message
    assert not Attachment.for_object(item).exists()


@pytest.mark.django_db
def test_delete_removes_row_and_file(client, lab):
    member = _user(lab, "m@x.de", ["Member"])
    item = _item(lab)
    client.force_login(member)
    client.post(reverse("attachments:add", args=["item", item.pk]), {"file": _pdf()})
    attachment = Attachment.for_object(item).get()
    storage, name = attachment.file.storage, attachment.file.name
    assert storage.exists(name)

    resp = client.post(reverse("attachments:delete", args=[attachment.pk]))
    assert resp.status_code == 302
    assert not Attachment.for_object(item).exists()
    assert not storage.exists(name)


@pytest.mark.django_db
def test_copy_to_duplicates_file_independently(lab):
    member = _user(lab, "m@x.de", ["Member"])
    req = Request.objects.create(lab=lab, item_name="Tips", requested_by=member)
    original = Attachment.objects.create(
        lab=lab,
        uploaded_by=member,
        target=req,
        file=SimpleUploadedFile("manual.pdf", b"manual body"),
        original_name="manual.pdf",
        size=11,
    )
    item = _item(lab)
    copy = original.copy_to(item)
    assert copy.pk != original.pk and copy.file.name != original.file.name
    assert copy.target == item and copy.original_name == "manual.pdf"

    original.delete()
    copy.refresh_from_db()
    with copy.file.open("rb") as fh:
        assert fh.read() == b"manual body"
