import pytest
from django.contrib.auth import get_user_model

from apps.tenancy.models import Lab, Role
from apps.tenancy.services import add_member, create_lab

User = get_user_model()


@pytest.mark.django_db
def test_create_lab_clones_template_roles():
    lab = create_lab(name="AG Baumann", item_id_prefix="agb")

    assert lab.slug == "ag-baumann"
    assert lab.item_id_prefix == "AGB"  # prefix upper-cased
    cloned = Role.objects.filter(lab=lab, is_template=False)
    template_names = set(Role.objects.filter(is_template=True).values_list("name", flat=True))
    assert set(cloned.values_list("name", flat=True)) == template_names
    # Lab manager clone carries every permission.
    manager = cloned.get(name="Lab manager")
    assert manager.permissions.filter(code="manage_lab").exists()


@pytest.mark.django_db
def test_allocate_item_id_is_sequential_and_frozen():
    lab = create_lab(name="Lab One", item_id_prefix="L1")
    first = lab.allocate_item_id()
    second = lab.allocate_item_id()
    assert first == "L1-00001"
    assert second == "L1-00002"
    assert Lab.objects.get(pk=lab.pk).next_item_number == 3


@pytest.mark.django_db
def test_user_can_resolves_union_of_role_permissions():
    lab = create_lab(name="Perm Lab", item_id_prefix="PL")
    viewer = User.objects.create_user(username="", email="v@x.de", password="pw")
    add_member(user=viewer, lab=lab, role_names=["Viewer"])

    assert viewer.can(lab, "view_inventory") is True
    assert viewer.can(lab, "approve_request") is False


@pytest.mark.django_db
def test_superuser_can_everything():
    lab = create_lab(name="Su Lab", item_id_prefix="SU")
    su = User.objects.create_superuser(username="", email="su@x.de", password="pw")
    assert su.can(lab, "manage_lab") is True


@pytest.mark.django_db
def test_permissions_do_not_leak_across_labs():
    lab_a = create_lab(name="Lab A", item_id_prefix="LA")
    lab_b = create_lab(name="Lab B", item_id_prefix="LB")
    user = User.objects.create_user(username="", email="u@x.de", password="pw")
    add_member(user=user, lab=lab_a, role_names=["Lab manager"])

    assert user.can(lab_a, "manage_lab") is True
    # No membership in lab B -> no rights there.
    assert user.can(lab_b, "manage_lab") is False
