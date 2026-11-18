"""Role-aware welcome tour, getting-started checklist, welcome email, empty states."""

import pytest
from django.urls import reverse

from apps.inventory.models import Item, Location
from apps.notifications.emails import build_welcome
from apps.tenancy.models import Membership, User
from apps.tenancy.onboarding import checklist, checklist_for_dashboard, tour_steps
from apps.tenancy.services import add_member, create_lab

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab(db):
    return create_lab(name="AG Start", item_id_prefix="ST")


def _user(lab, email, roles, **fields):
    user = User.objects.create_user(username="", email=email, password="pw", **fields)
    add_member(user=user, lab=lab, role_names=roles)
    return user


# --- Tour --------------------------------------------------------------------------------


def test_tour_follows_the_members_permissions(lab):
    viewer = tour_steps(_user(lab, "v@x.de", ["Viewer"]), lab)
    member = tour_steps(_user(lab, "m@x.de", ["Member"]), lab)
    manager = tour_steps(_user(lab, "b@x.de", ["Lab manager"]), lab)

    assert viewer == ["profile", "find", "scan", "rights"]
    assert "request" in member and "receive" in member
    assert "approve" not in member and "setup" not in member
    assert {"approve", "order", "sign", "setup"} <= set(manager)
    assert manager[0] == "profile" and manager[-1] == "rights"


def test_tour_page_numbers_only_the_shown_steps(client, lab):
    client.force_login(_user(lab, "v@x.de", ["Viewer"]))
    page = client.get(reverse("tenancy:onboarding")).content.decode()
    assert "Order things" not in page and "Set up your lab" not in page
    assert "4 · Know what you can do" in page


# --- Checklist ---------------------------------------------------------------------------


def test_manager_checklist_ticks_itself_off_from_the_data(lab):
    manager = _user(lab, "b@x.de", ["Lab manager"])
    before = {item.label: item.done for item in checklist(manager, lab)}
    assert before["Add storage locations"] is False
    assert before["Bring in your inventory"] is False

    Location.objects.create(lab=lab, name="Fridge 1")
    Item.objects.create(lab=lab, human_id="ST-1", name="Ethanol")
    after = {item.label: item.done for item in checklist(manager, lab)}
    assert after["Add storage locations"] is True
    assert after["Bring in your inventory"] is True


def test_members_only_see_personal_steps(lab):
    labels = [item.label for item in checklist(_user(lab, "m@x.de", ["Member"]), lab)]
    assert labels == ["Set your display name", "Read the welcome tour", "Raise your first request"]


def test_checklist_disappears_when_done(lab):
    from django.utils import timezone

    viewer = _user(lab, "v@x.de", ["Viewer"], friendly_name="Vera")
    assert checklist_for_dashboard(viewer, lab)  # the tour is still unread
    viewer.onboarding_seen_at = timezone.now()
    assert checklist_for_dashboard(viewer, lab) == []


def test_dashboard_shows_the_checklist_until_hidden(client, lab):
    manager = _user(lab, "b@x.de", ["Lab manager"])
    client.force_login(manager)
    assert "Getting started" in client.get("/").content.decode()

    client.post(reverse("tenancy:checklist_dismiss"))

    assert Membership.objects.get(user=manager, lab=lab).checklist_dismissed_at is not None
    assert "Getting started" not in client.get("/").content.decode()


# --- Welcome email -----------------------------------------------------------------------


def test_welcome_email_names_the_inviter_and_the_roles(lab):
    inviter = User(email="boss@x.de", friendly_name="Bo Boss")
    newcomer = User(email="new@x.de")
    content = build_welcome(
        newcomer, lab, "https://lab/set", invited_by=inviter, roles=["Member", "Viewer"]
    )
    assert "by Bo Boss (boss@x.de)" in content.body
    assert "Member, Viewer" in content.body


def test_adding_a_member_sends_the_detailed_welcome(
    client, lab, mailoutbox, django_capture_on_commit_callbacks
):
    from apps.tenancy.models import Role

    manager = _user(lab, "b@x.de", ["Lab manager"], friendly_name="Bo Boss")
    client.force_login(manager)
    member_role = Role.objects.get(lab=lab, name="Member")
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("manage:member_add"), {"email": "new@x.de", "roles": [member_role.pk]})
    assert "by Bo Boss" in mailoutbox[-1].body
    assert "Your roles:" in mailoutbox[-1].body and "Member" in mailoutbox[-1].body


# --- Empty states ------------------------------------------------------------------------


def test_empty_inventory_points_managers_to_import(client, lab):
    client.force_login(_user(lab, "b@x.de", ["Lab manager"]))
    page = client.get(reverse("inventory:item_list")).content.decode()
    assert "The inventory is still empty" in page and "Import a spreadsheet" in page

    filtered = client.get(reverse("inventory:item_list"), {"q": "nothing"}).content.decode()
    assert "No items match" in filtered


def test_empty_request_list_invites_the_first_request(client, lab):
    client.force_login(_user(lab, "m@x.de", ["Member"]))
    page = client.get(reverse("procurement:request_list")).content.decode()
    assert "No requests yet" in page and "Raise the first request" in page
