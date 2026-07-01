"""Comment posting: creation on items/requests, gating, and tenant scoping."""

import pytest
from django.urls import reverse

from apps.comments.models import Comment
from apps.inventory.models import Item
from apps.procurement.models import Request
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


def _user(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


def _item(lab, name: str = "Ethanol") -> Item:
    return Item.objects.create(lab=lab, human_id=lab.allocate_item_id(), name=name)


@pytest.mark.django_db
def test_comment_on_item_and_shows_on_detail(client, lab):
    viewer = _user(lab, "v@x.de", ["Viewer"])
    item = _item(lab)
    client.force_login(viewer)
    resp = client.post(reverse("comments:add", args=["item", item.pk]), {"body": "Looks fine"})
    assert resp.status_code == 302
    assert resp["Location"].endswith("#comments")

    comment = Comment.for_object(item).get()
    assert comment.body == "Looks fine"
    assert comment.author == viewer and comment.lab == lab

    detail = client.get(reverse("inventory:item_detail", args=[item.pk]))
    assert b"Looks fine" in detail.content


@pytest.mark.django_db
def test_comment_on_request(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    req = Request.objects.create(lab=lab, item_name="Tips", requested_by=member)
    client.force_login(member)
    resp = client.post(reverse("comments:add", args=["request", req.pk]), {"body": "Any update?"})
    assert resp.status_code == 302
    assert Comment.for_object(req).get().body == "Any update?"


@pytest.mark.django_db
def test_empty_comment_is_rejected(client, lab):
    viewer = _user(lab, "v@x.de", ["Viewer"])
    item = _item(lab)
    client.force_login(viewer)
    resp = client.post(reverse("comments:add", args=["item", item.pk]), {"body": "   "})
    assert resp.status_code == 302
    assert Comment.for_object(item).count() == 0


@pytest.mark.django_db
def test_comment_requires_view_permission(client, lab):
    nobody = User.objects.create_user(username="", email="n@x.de", password="pw")
    add_member(user=nobody, lab=lab)  # member of the lab but no roles -> no view_inventory
    item = _item(lab)
    client.force_login(nobody)
    resp = client.post(reverse("comments:add", args=["item", item.pk]), {"body": "hi"})
    assert resp.status_code == 403
    assert Comment.for_object(item).count() == 0


@pytest.mark.django_db
def test_cannot_comment_on_other_labs_object(client, lab):
    viewer = _user(lab, "v@x.de", ["Viewer"])
    other = create_lab(name="Other", item_id_prefix="OT")
    foreign = _item(other)
    client.force_login(viewer)
    assert (
        client.post(reverse("comments:add", args=["item", foreign.pk]), {"body": "hi"}).status_code
        == 404
    )


@pytest.mark.django_db
def test_unknown_model_is_404(client, lab):
    client.force_login(_user(lab, "v@x.de", ["Viewer"]))
    assert (
        client.post(reverse("comments:add", args=["budget", 1]), {"body": "hi"}).status_code == 404
    )
