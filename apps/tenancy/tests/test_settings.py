"""Personal settings page: friendly name plus permission-gated notification preferences."""

import pytest
from django.urls import reverse

from apps.tenancy.models import Membership, NotificationFrequency, User
from apps.tenancy.services import add_member, create_lab

URL = reverse("tenancy:settings")


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


def _user(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


@pytest.mark.django_db
def test_manager_sees_account_and_both_notification_settings(client, lab):
    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    resp = client.get(URL)
    assert resp.status_code == 200
    assert b"Friendly name" in resp.content
    assert b"needs approval" in resp.content
    assert b"changes status" in resp.content


@pytest.mark.django_db
def test_member_sees_only_request_updates(client, lab):
    # Member can raise requests but not approve, so only the update setting shows.
    client.force_login(_user(lab, "member@x.de", ["Member"]))
    resp = client.get(URL)
    assert resp.status_code == 200
    assert b"changes status" in resp.content
    assert b"needs approval" not in resp.content


@pytest.mark.django_db
def test_viewer_sees_account_but_no_notifications(client, lab):
    client.force_login(_user(lab, "viewer@x.de", ["Viewer"]))
    resp = client.get(URL)
    assert resp.status_code == 200
    # The account section is always available; notification categories are not.
    assert b"Friendly name" in resp.content
    assert b"changes status" not in resp.content
    assert b"needs approval" not in resp.content


@pytest.mark.django_db
def test_can_set_and_clear_friendly_name(client, lab):
    user = _user(lab, "viewer@x.de", ["Viewer"])
    client.force_login(user)

    resp = client.post(URL, {"friendly_name": "Vera Viewer"})
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.friendly_name == "Vera Viewer"

    client.post(URL, {"friendly_name": ""})
    user.refresh_from_db()
    assert user.friendly_name == ""


@pytest.mark.django_db
def test_member_can_save_preference(client, lab):
    user = _user(lab, "member@x.de", ["Member"])
    client.force_login(user)
    resp = client.post(URL, {"request_update_notifications": NotificationFrequency.OFF})
    assert resp.status_code == 302
    membership = Membership.objects.get(user=user, lab=lab)
    assert membership.request_update_notifications == NotificationFrequency.OFF


@pytest.mark.django_db
def test_effective_permissions_show_granted_and_missing(client, lab):
    client.force_login(_user(lab, "viewer@x.de", ["Viewer"]))
    resp = client.get(URL)
    assert b"Effective permissions" in resp.content
    held = {p["code"]: p["held"] for p in resp.context["effective_permissions"]}
    assert held["view_inventory"] is True
    assert held["view_requests"] is True
    assert held["manage_lab"] is False
    assert held["accept_forwards"] is False


@pytest.mark.django_db
def test_effective_permissions_cover_the_whole_catalog_in_order(client, lab):
    from apps.tenancy.catalog import PERMISSION_CATALOG

    client.force_login(_user(lab, "member@x.de", ["Member"]))
    resp = client.get(URL)
    codes = [p["code"] for p in resp.context["effective_permissions"]]
    assert codes == [code for code, _ in PERMISSION_CATALOG]


@pytest.mark.django_db
def test_superuser_holds_every_permission(client, lab):
    user = _user(lab, "root@x.de", ["Viewer"])
    user.is_superuser = True
    user.save()
    client.force_login(user)
    resp = client.get(URL)
    assert all(p["held"] for p in resp.context["effective_permissions"])


@pytest.mark.django_db
def test_member_cannot_set_a_field_they_lack_rights_for(client, lab):
    # A Member has no approve_request, so posting that field must not change it.
    user = _user(lab, "member@x.de", ["Member"])
    client.force_login(user)
    client.post(
        URL,
        {
            "request_update_notifications": NotificationFrequency.DAILY,
            "approval_notifications": NotificationFrequency.OFF,  # should be ignored
        },
    )
    membership = Membership.objects.get(user=user, lab=lab)
    assert membership.request_update_notifications == NotificationFrequency.DAILY
    assert membership.approval_notifications == NotificationFrequency.IMMEDIATE  # unchanged
