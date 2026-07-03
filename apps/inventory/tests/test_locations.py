"""Location hierarchy tests: path rendering, tree ordering, subtree filtering, and the
manage-area CRUD (create with a parent, move without cycles, cascade-delete warning)."""

import pytest
from django.urls import reverse

from apps.inventory.models import Item, Location
from apps.tenancy.manage_forms import LocationForm
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


@pytest.fixture
def tree(lab):
    """Room 376 -> (Fridge A -> Shelf 2, Freezer B); Room 380 standalone."""
    room = Location.objects.create(lab=lab, name="Room 376", room_number="376")
    fridge = Location.objects.create(lab=lab, name="Fridge A", parent=room)
    shelf = Location.objects.create(lab=lab, name="Shelf 2", parent=fridge)
    freezer = Location.objects.create(lab=lab, name="Freezer B", parent=room)
    other_room = Location.objects.create(lab=lab, name="Room 380")
    return {
        "room": room,
        "fridge": fridge,
        "shelf": shelf,
        "freezer": freezer,
        "other_room": other_room,
    }


def _member(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


# --- Model helpers ----------------------------------------------------------------------


@pytest.mark.django_db
def test_full_path_walks_ancestors(tree):
    assert tree["shelf"].full_path == "Room 376 / Fridge A / Shelf 2"
    assert tree["room"].full_path == "Room 376"
    assert str(tree["shelf"]) == "Room 376 / Fridge A / Shelf 2"


@pytest.mark.django_db
def test_tree_for_lab_is_depth_first_with_depths(lab, tree):
    ordered = Location.tree_for_lab(lab)
    assert [loc.name for loc in ordered] == [
        "Room 376",
        "Freezer B",
        "Fridge A",
        "Shelf 2",
        "Room 380",
    ]
    assert [loc.depth for loc in ordered] == [0, 1, 1, 2, 0]


@pytest.mark.django_db
def test_tree_for_lab_is_lab_scoped(lab, tree):
    other = create_lab(name="Other", item_id_prefix="OT")
    Location.objects.create(lab=other, name="Foreign room")
    assert all(loc.lab_id == lab.pk for loc in Location.tree_for_lab(lab))


@pytest.mark.django_db
def test_subtree_pks_covers_descendants_not_siblings(lab, tree):
    pks = set(Location.subtree_pks(lab, tree["room"].pk))
    assert pks == {tree["room"].pk, tree["fridge"].pk, tree["shelf"].pk, tree["freezer"].pk}
    assert Location.subtree_pks(lab, tree["shelf"].pk) == [tree["shelf"].pk]


@pytest.mark.django_db
def test_attach_path_names_bulk_caches_paths(lab, tree, django_assert_num_queries):
    shelf = Location.objects.get(pk=tree["shelf"].pk)  # fresh instance, no cache
    with django_assert_num_queries(1):
        Location.attach_path_names(lab, [shelf])
        assert shelf.full_path == "Room 376 / Fridge A / Shelf 2"


# --- Item list: whole-subtree filtering & path display -----------------------------------


def _make_item(lab, name, location=None) -> Item:
    return Item.objects.create(
        lab=lab, human_id=lab.allocate_item_id(), name=name, location=location
    )


@pytest.mark.django_db
def test_location_facet_includes_whole_subtree(client, lab, tree):
    _make_item(lab, "Taq polymerase", tree["shelf"])
    _make_item(lab, "Ligase", tree["freezer"])
    _make_item(lab, "Elsewhere", tree["other_room"])
    client.force_login(_member(lab, "view@x.de", ["Viewer"]))

    resp = client.get(reverse("inventory:item_list"), {"location": tree["room"].pk})
    assert b"Taq polymerase" in resp.content  # nested two levels down
    assert b"Ligase" in resp.content
    assert b"Elsewhere" not in resp.content


@pytest.mark.django_db
def test_item_list_shows_full_location_path(client, lab, tree):
    _make_item(lab, "Taq polymerase", tree["shelf"])
    client.force_login(_member(lab, "view@x.de", ["Viewer"]))
    resp = client.get(reverse("inventory:item_list"))
    assert b"Room 376 / Fridge A / Shelf 2" in resp.content


@pytest.mark.django_db
def test_location_facet_ignores_garbage_value(client, lab, tree):
    _make_item(lab, "Taq polymerase", tree["shelf"])
    client.force_login(_member(lab, "view@x.de", ["Viewer"]))
    resp = client.get(reverse("inventory:item_list"), {"location": "not-a-pk"})
    assert resp.status_code == 200


# --- Manage CRUD ------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_nested_location(client, lab, tree):
    client.force_login(_member(lab, "boss@x.de", ["Lab manager"]))
    resp = client.post(
        reverse("manage:add", args=["locations"]),
        {"name": "Drawer 1", "parent": tree["fridge"].pk, "room_number": ""},
    )
    assert resp.status_code == 302
    drawer = Location.objects.get(lab=lab, name="Drawer 1")
    assert drawer.parent == tree["fridge"]
    assert drawer.full_path == "Room 376 / Fridge A / Drawer 1"


@pytest.mark.django_db
def test_move_location_to_new_parent(client, lab, tree):
    client.force_login(_member(lab, "boss@x.de", ["Lab manager"]))
    resp = client.post(
        reverse("manage:edit", args=["locations", tree["fridge"].pk]),
        {"name": "Fridge A", "parent": tree["other_room"].pk, "room_number": ""},
    )
    assert resp.status_code == 302
    tree["fridge"].refresh_from_db()
    assert tree["fridge"].parent == tree["other_room"]


@pytest.mark.django_db
def test_cannot_move_location_into_own_subtree(lab, tree):
    form = LocationForm(
        {"name": "Room 376", "parent": tree["shelf"].pk, "room_number": "376"},
        instance=tree["room"],
        lab=lab,
    )
    assert not form.is_valid()
    assert "parent" in form.errors


@pytest.mark.django_db
def test_parent_choices_exclude_own_subtree_and_other_labs(lab, tree):
    other = create_lab(name="Other", item_id_prefix="OT")
    foreign = Location.objects.create(lab=other, name="Foreign room")
    form = LocationForm(instance=tree["fridge"], lab=lab)
    offered = {pk for pk, _ in form.fields["parent"].choices if pk}
    assert tree["fridge"].pk not in offered
    assert tree["shelf"].pk not in offered
    assert foreign.pk not in offered
    assert tree["room"].pk in offered


@pytest.mark.django_db
def test_delete_warns_about_nested_locations_and_keeps_items(client, lab, tree):
    item = _make_item(lab, "Taq polymerase", tree["shelf"])
    client.force_login(_member(lab, "boss@x.de", ["Lab manager"]))

    resp = client.get(reverse("manage:delete", args=["locations", tree["room"].pk]))
    assert b"3 nested locations" in resp.content

    client.post(reverse("manage:delete", args=["locations", tree["room"].pk]))
    assert not Location.objects.filter(pk=tree["shelf"].pk).exists()
    item.refresh_from_db()
    assert item.location is None  # the item survives, just unplaced
