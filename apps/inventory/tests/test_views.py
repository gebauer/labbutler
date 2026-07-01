"""Inventory view tests: lab scoping, search, permissions, and create/edit/delete.

These exercise the public HTTP contract (status codes, what's rendered, what's written)
rather than view internals, and assert the hard rules: tenant isolation, frozen human
IDs, and fail-closed permission checks.
"""

import pytest
from django.urls import reverse

from apps.audit.models import AuditEntry
from apps.inventory.models import HazardStatement, Item, Tag
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


@pytest.fixture
def other_lab(db):
    return create_lab(name="AG Other", item_id_prefix="OTH")


def _member(email: str, lab, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


@pytest.fixture
def manager(lab):
    return _member("mgr@x.de", lab, ["Lab manager"])


@pytest.fixture
def viewer(lab):
    return _member("view@x.de", lab, ["Viewer"])


def _make_item(lab, name="Tris buffer", **kwargs) -> Item:
    return Item.objects.create(lab=lab, human_id=lab.allocate_item_id(), name=name, **kwargs)


@pytest.mark.django_db
def test_list_requires_login(client, lab):
    resp = client.get(reverse("inventory:item_list"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_member_without_lab_gets_empty_state(client):
    user = User.objects.create_user(username="", email="nolab@x.de", password="pw")
    client.force_login(user)
    resp = client.get(reverse("inventory:item_list"))
    assert resp.status_code == 403
    assert b"No lab yet" in resp.content


@pytest.mark.django_db
def test_viewer_sees_items_but_no_new_button(client, lab, viewer):
    _make_item(lab, name="Tris buffer")
    client.force_login(viewer)
    resp = client.get(reverse("inventory:item_list"))
    assert resp.status_code == 200
    assert b"Tris buffer" in resp.content
    # No manage_inventory -> the create affordance is hidden.
    assert reverse("inventory:item_create").encode() not in resp.content


@pytest.mark.django_db
def test_list_is_scoped_to_current_lab(client, lab, other_lab, manager):
    _make_item(lab, name="Mine")
    _make_item(other_lab, name="NotMine")
    client.force_login(manager)
    resp = client.get(reverse("inventory:item_list"))
    assert b"Mine" in resp.content
    assert b"NotMine" not in resp.content


@pytest.mark.django_db
def test_search_filters_by_query(client, lab, manager):
    _make_item(lab, name="Sodium chloride")
    _make_item(lab, name="Ethanol")
    client.force_login(manager)
    resp = client.get(reverse("inventory:item_list"), {"q": "ethanol"})
    assert b"Ethanol" in resp.content
    assert b"Sodium chloride" not in resp.content


@pytest.mark.django_db
def test_filter_by_tag_name(client, lab, manager):
    solvent = Tag.objects.create(lab=lab, name="solvent")
    tagged = _make_item(lab, name="Ethanol")
    tagged.tags.add(solvent)
    _make_item(lab, name="Sodium chloride")
    client.force_login(manager)
    # The tag combobox filters by name (case-insensitive, substring).
    resp = client.get(reverse("inventory:item_list"), {"tag": "SOLV"})
    assert b"Ethanol" in resp.content
    assert b"Sodium chloride" not in resp.content


@pytest.mark.django_db
def test_htmx_request_returns_partial(client, lab, manager):
    _make_item(lab, name="Tris buffer")
    client.force_login(manager)
    resp = client.get(reverse("inventory:item_list"), HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    # Partial: the results div, not the full page chrome.
    assert b'id="item-results"' in resp.content
    assert b"<html" not in resp.content


@pytest.mark.django_db
def test_cards_view_renders_cards_not_table(client, lab, manager):
    _make_item(lab, name="Carditem")
    client.force_login(manager)
    resp = client.get(reverse("inventory:item_list"), {"view": "cards"})
    assert resp.status_code == 200
    assert b"Carditem" in resp.content
    assert b"<table" not in resp.content  # rendered as cards, not a table


@pytest.mark.django_db
def test_view_mode_persists_in_session(client, lab, manager):
    _make_item(lab, name="Persisted")
    client.force_login(manager)
    # Default is the table.
    assert b"<table" in client.get(reverse("inventory:item_list")).content
    # Switching to cards sticks on later requests that omit ?view.
    client.get(reverse("inventory:item_list"), {"view": "cards"})
    assert b"<table" not in client.get(reverse("inventory:item_list")).content
    # And switching back to the table sticks too.
    client.get(reverse("inventory:item_list"), {"view": "table"})
    assert b"<table" in client.get(reverse("inventory:item_list")).content


@pytest.mark.django_db
def test_detail_404_for_other_lab_item(client, lab, other_lab, manager):
    foreign = _make_item(other_lab, name="NotMine")
    client.force_login(manager)
    resp = client.get(reverse("inventory:item_detail", args=[foreign.pk]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_create_allocates_frozen_human_id_and_audits(client, lab, manager):
    client.force_login(manager)
    resp = client.post(
        reverse("inventory:item_create"),
        {"name": "New reagent", "price_currency": "", "tags": []},
    )
    assert resp.status_code == 302
    item = Item.objects.get(name="New reagent")
    assert item.human_id == "AGB-00001"
    assert item.lab == lab
    assert AuditEntry.objects.filter(
        action="inventory.item_created", target_id=str(item.pk)
    ).exists()


@pytest.mark.django_db
def test_create_forbidden_for_viewer(client, lab, viewer):
    client.force_login(viewer)
    resp = client.post(reverse("inventory:item_create"), {"name": "Nope", "tags": []})
    assert resp.status_code == 403
    assert not Item.objects.filter(name="Nope").exists()


@pytest.mark.django_db
def test_edit_keeps_human_id_and_updates_fields(client, lab, manager):
    item = _make_item(lab, name="Old name")
    frozen_id = item.human_id
    client.force_login(manager)
    resp = client.post(
        reverse("inventory:item_edit", args=[item.pk]),
        {"name": "New name", "tags": []},
    )
    assert resp.status_code == 302
    item.refresh_from_db()
    assert item.name == "New name"
    assert item.human_id == frozen_id


@pytest.mark.django_db
def test_delete_removes_item_and_audits(client, lab, manager):
    item = _make_item(lab, name="Doomed")
    pk = item.pk
    client.force_login(manager)
    resp = client.post(reverse("inventory:item_delete", args=[pk]))
    assert resp.status_code == 302
    assert not Item.objects.filter(pk=pk).exists()
    assert AuditEntry.objects.filter(action="inventory.item_deleted", target_id=str(pk)).exists()


@pytest.mark.django_db
def test_switch_lab_updates_session(client, lab, other_lab):
    user = User.objects.create_user(username="", email="multi@x.de", password="pw")
    add_member(user=user, lab=lab, role_names=["Viewer"])
    add_member(user=user, lab=other_lab, role_names=["Viewer"])
    _make_item(lab, name="InLabA")
    _make_item(other_lab, name="InLabB")
    client.force_login(user)

    resp = client.post(reverse("inventory:switch_lab", args=[other_lab.slug]))
    assert resp.status_code == 302
    listing = client.get(reverse("inventory:item_list"))
    assert b"InLabB" in listing.content
    assert b"InLabA" not in listing.content


@pytest.mark.django_db
def test_detail_shows_hazard_statement_on_hover(client, lab, manager):
    item = _make_item(lab, name="Ethanol")
    item.hazards.add(HazardStatement.objects.get(code="H319"))  # seeded with text
    client.force_login(manager)
    resp = client.get(reverse("inventory:item_detail", args=[item.pk]))
    assert resp.status_code == 200
    assert b"H319" in resp.content
    # The general GHS sentence for the code appears in the hover title.
    assert b"Causes serious eye irritation" in resp.content


@pytest.mark.django_db
def test_filter_by_location(client, lab, manager):
    from apps.inventory.models import Location

    fridge = Location.objects.create(lab=lab, name="Fridge 2")
    _make_item(lab, name="Cold thing", location=fridge)
    _make_item(lab, name="Bench thing")
    client.force_login(manager)
    resp = client.get(reverse("inventory:item_list"), {"location": fridge.pk})
    assert b"Cold thing" in resp.content
    assert b"Bench thing" not in resp.content


@pytest.mark.django_db
def test_filter_by_supplier(client, lab, manager):
    from apps.procurement.models import Vendor

    sigma = Vendor.objects.create(lab=lab, name="Sigma")
    _make_item(lab, name="From Sigma", vendor=sigma)
    _make_item(lab, name="From nowhere")
    client.force_login(manager)
    resp = client.get(reverse("inventory:item_list"), {"vendor": sigma.pk})
    assert b"From Sigma" in resp.content
    assert b"From nowhere" not in resp.content


@pytest.mark.django_db
def test_filter_by_owner_and_combined(client, lab, manager):
    owner = User.objects.create_user(username="", email="owner@x.de", password="pw")
    _make_item(lab, name="Owned solvent", owner=owner)
    _make_item(lab, name="Owned other", owner=owner)
    _make_item(lab, name="Unowned")
    client.force_login(manager)
    resp = client.get(reverse("inventory:item_list"), {"owner": owner.pk, "q": "solvent"})
    assert b"Owned solvent" in resp.content
    assert b"Owned other" not in resp.content  # narrowed further by the query
    assert b"Unowned" not in resp.content
