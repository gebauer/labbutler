"""Lab-admin CRUD tests: permission gating, tenant scoping, and the shared views."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.inventory.models import FieldDefinition
from apps.procurement.models import Budget, Vendor
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


def _user(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


@pytest.mark.django_db
def test_admin_requires_manage_lab(client, lab):
    client.force_login(_user(lab, "member@x.de", ["Member"]))  # no manage_lab
    assert client.get(reverse("manage:index")).status_code == 403
    assert client.get(reverse("manage:list", args=["suppliers"])).status_code == 403


@pytest.mark.django_db
def test_manager_sees_landing_with_sections(client, lab):
    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    resp = client.get(reverse("manage:index"))
    assert resp.status_code == 200
    assert b"Suppliers" in resp.content and b"Custom fields" in resp.content


@pytest.mark.django_db
def test_create_supplier(client, lab):
    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    resp = client.post(reverse("manage:add", args=["suppliers"]), {"name": "Sigma"})
    assert resp.status_code == 302
    assert Vendor.objects.get(name="Sigma").lab == lab


@pytest.mark.django_db
def test_edit_then_delete_budget(client, lab):
    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    budget = Budget.objects.create(lab=lab, number="KST1", name="Grant")
    client.post(
        reverse("manage:edit", args=["budgets", budget.pk]),
        {"number": "KST1", "name": "Grant X", "owner": ""},
    )
    budget.refresh_from_db()
    assert budget.name == "Grant X"
    client.post(reverse("manage:delete", args=["budgets", budget.pk]))
    assert not Budget.objects.filter(pk=budget.pk).exists()


@pytest.mark.django_db
def test_custom_field_key_is_frozen_on_edit(client, lab):
    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    fd = FieldDefinition.objects.create(lab=lab, key="purity", label="Purity", data_type="text")
    client.post(
        reverse("manage:edit", args=["fields", fd.pk]),
        {"key": "changed", "label": "Purity %", "data_type": "text"},
    )
    fd.refresh_from_db()
    assert fd.key == "purity"  # disabled field: submitted key ignored
    assert fd.label == "Purity %"


@pytest.mark.django_db
def test_cannot_touch_other_labs_rows(client, lab):
    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    other = create_lab(name="Other", item_id_prefix="OT")
    foreign = Vendor.objects.create(lab=other, name="Foreign")
    assert client.get(reverse("manage:edit", args=["suppliers", foreign.pk])).status_code == 404


@pytest.mark.django_db
def test_unknown_kind_is_404(client, lab):
    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    assert client.get(reverse("manage:list", args=["bogus"])).status_code == 404


@pytest.mark.django_db
def test_settings_update(client, lab):
    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    resp = client.post(
        reverse("manage:settings"), {"name": "AG B New", "default_vat_rate": "0.07"}
    )
    assert resp.status_code == 302
    lab.refresh_from_db()
    assert lab.name == "AG B New"
    assert lab.default_vat_rate == Decimal("0.07")


@pytest.mark.django_db
def test_settings_rejects_out_of_range_vat(client, lab):
    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    resp = client.post(reverse("manage:settings"), {"name": "AG B", "default_vat_rate": "1.5"})
    assert resp.status_code == 200  # re-rendered with an error
    lab.refresh_from_db()
    assert lab.default_vat_rate == Decimal("0.19")  # unchanged
