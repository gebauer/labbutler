"""A lab must never be left without a member holding ``manage_lab``."""

import pytest
from django.urls import reverse

from apps.tenancy.models import Membership, Permission, Role, User
from apps.tenancy.services import add_member, create_lab, lab_has_manager

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab(db):
    return create_lab(name="AG Solo", item_id_prefix="SOLO")


@pytest.fixture
def boss(client, lab):
    user = User.objects.create_user(username="", email="boss@x.de", password="pw")
    add_member(user=user, lab=lab, role_names=["Lab manager"])
    client.force_login(user)
    return user


def _manager_role(lab) -> Role:
    return Role.objects.get(lab=lab, name="Lab manager")


def test_sole_manager_cannot_drop_their_own_manager_role(client, lab, boss):
    member_role = Role.objects.get(lab=lab, name="Member")
    membership = Membership.objects.get(user=boss, lab=lab)

    resp = client.post(
        reverse("manage:member_edit", args=[membership.pk]), {"roles": [member_role.pk]}
    )

    assert resp.status_code == 200  # form re-rendered, not saved
    assert "without anyone who can manage it" in resp.content.decode()
    assert lab_has_manager(lab)


def test_manage_lab_cannot_be_removed_from_the_only_manager_role(client, lab, boss):
    role = _manager_role(lab)
    kept = role.permissions.exclude(code="manage_lab").values_list("pk", flat=True)

    resp = client.post(
        reverse("manage:role_edit", args=[role.pk]), {"name": role.name, "permissions": kept}
    )

    assert resp.status_code == 200
    assert role.permissions.filter(code="manage_lab").exists()


def test_the_only_manager_role_cannot_be_deleted(client, lab, boss):
    role = _manager_role(lab)
    client.post(reverse("manage:role_delete", args=[role.pk]))
    assert Role.objects.filter(pk=role.pk).exists()


def test_superuser_cannot_remove_the_last_manager(client, lab, boss):
    admin = User.objects.create_superuser(username="", email="root@x.de", password="pw")
    client.force_login(admin)
    client.post(
        reverse("manage:member_remove", args=[Membership.objects.get(user=boss, lab=lab).pk])
    )
    assert Membership.objects.filter(user=boss, lab=lab).exists()


def test_changes_are_allowed_while_another_manager_remains(client, lab, boss):
    other = User.objects.create_user(username="", email="co@x.de", password="pw")
    add_member(user=other, lab=lab, role_names=["Lab manager"])
    membership = Membership.objects.get(user=boss, lab=lab)
    member_role = Role.objects.get(lab=lab, name="Member")

    resp = client.post(
        reverse("manage:member_edit", args=[membership.pk]), {"roles": [member_role.pk]}
    )

    assert resp.status_code == 302
    assert not boss.can(lab, "manage_lab")
    assert other.can(lab, "manage_lab")


def test_lab_without_manager_is_not_blocked_from_unrelated_edits(client, lab):
    admin = User.objects.create_superuser(username="", email="root@x.de", password="pw")
    client.force_login(admin)
    role = Role.objects.get(lab=lab, name="Viewer")
    perms = Permission.objects.filter(code="view_inventory").values_list("pk", flat=True)
    resp = client.post(
        reverse("manage:role_edit", args=[role.pk]), {"name": "Readers", "permissions": perms}
    )
    assert resp.status_code == 302
