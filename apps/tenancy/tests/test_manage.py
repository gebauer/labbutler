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
        reverse("manage:settings"),
        {"name": "AG B New", "default_vat_rate": "0.07", "default_currency": "USD"},
    )
    assert resp.status_code == 302
    lab.refresh_from_db()
    assert lab.name == "AG B New"
    assert lab.default_vat_rate == Decimal("0.07")
    assert lab.default_currency == "USD"


@pytest.mark.django_db
def test_settings_rejects_out_of_range_vat(client, lab):
    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    resp = client.post(reverse("manage:settings"), {"name": "AG B", "default_vat_rate": "1.5"})
    assert resp.status_code == 200  # re-rendered with an error
    lab.refresh_from_db()
    assert lab.default_vat_rate == Decimal("0.19")  # unchanged


@pytest.mark.django_db
def test_members_and_roles_require_manage_lab(client, lab):
    client.force_login(_user(lab, "member@x.de", ["Member"]))
    assert client.get(reverse("manage:members")).status_code == 403
    assert client.get(reverse("manage:roles")).status_code == 403


@pytest.mark.django_db
def test_add_member_creates_user_and_membership(client, lab):
    from apps.tenancy.models import Membership, Role

    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    viewer = Role.objects.get(lab=lab, name="Viewer")
    resp = client.post(reverse("manage:member_add"), {"email": "New@x.de", "roles": [viewer.pk]})
    assert resp.status_code == 302
    membership = Membership.objects.get(user__email__iexact="new@x.de", lab=lab)
    assert membership.user.email == "New@x.de"  # stored casing preserved for readability
    assert set(membership.roles.values_list("name", flat=True)) == {"Viewer"}


@pytest.mark.django_db
def test_add_member_sends_welcome_only_to_brand_new_users(
    client, lab, mailoutbox, monkeypatch, django_capture_on_commit_callbacks
):
    from apps.notifications import tasks

    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    # Run the enqueued task inline instead of dispatching to a Celery worker.
    monkeypatch.setattr(
        tasks.send_welcome_email,
        "delay",
        lambda *args, **kwargs: tasks.send_welcome_email(*args, **kwargs),
    )

    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("manage:member_add"), {"email": "new@x.de", "roles": []})
    assert [m.to for m in mailoutbox] == [["new@x.de"]]
    assert lab.name in mailoutbox[0].subject

    # Adding an already-existing account to the lab must not send a welcome.
    _user(lab, "known@x.de", ["Viewer"])
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("manage:member_add"), {"email": "known@x.de", "roles": []})
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_add_member_matches_existing_email_case_insensitively(client, lab):
    from apps.tenancy.models import Membership, User

    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    existing = _user(lab, "Alice@x.de", ["Viewer"])

    resp = client.post(reverse("manage:member_add"), {"email": "ALICE@x.de", "roles": []})
    assert resp.status_code == 302
    # No second account is created and the original casing is untouched.
    assert User.objects.filter(email__iexact="alice@x.de").count() == 1
    assert Membership.objects.filter(user=existing, lab=lab).count() == 1
    existing.refresh_from_db()
    assert existing.email == "Alice@x.de"


@pytest.mark.django_db
def test_members_search_matches_email_and_friendly_name(client, lab):
    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    alice = _user(lab, "alice@x.de", ["Viewer"])
    alice.friendly_name = "Alice Wonder"
    alice.save(update_fields=["friendly_name"])
    _user(lab, "bob@x.de", ["Viewer"])

    by_name = client.get(reverse("manage:members"), {"q": "wonder"})
    assert b"alice@x.de" in by_name.content and b"bob@x.de" not in by_name.content

    by_email = client.get(reverse("manage:members"), {"q": "bob@"})
    assert b"bob@x.de" in by_email.content and b"alice@x.de" not in by_email.content


@pytest.mark.django_db
def test_member_edit_roles(client, lab):
    from apps.tenancy.models import Membership, Role

    boss = _user(lab, "boss@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Viewer"])
    membership = Membership.objects.get(user=member, lab=lab)
    manager_role = Role.objects.get(lab=lab, name="Lab manager")
    client.force_login(boss)
    client.post(reverse("manage:member_edit", args=[membership.pk]), {"roles": [manager_role.pk]})
    assert set(membership.roles.values_list("name", flat=True)) == {"Lab manager"}


@pytest.mark.django_db
def test_cannot_remove_self_but_can_remove_others(client, lab):
    from apps.tenancy.models import Membership

    boss = _user(lab, "boss@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Viewer"])
    own = Membership.objects.get(user=boss, lab=lab)
    other = Membership.objects.get(user=member, lab=lab)
    client.force_login(boss)
    client.post(reverse("manage:member_remove", args=[own.pk]))
    assert Membership.objects.filter(pk=own.pk).exists()  # self kept
    client.post(reverse("manage:member_remove", args=[other.pk]))
    assert not Membership.objects.filter(pk=other.pk).exists()


@pytest.mark.django_db
def test_create_edit_delete_role_permissions(client, lab):
    from apps.tenancy.models import Permission, Role

    client.force_login(_user(lab, "boss@x.de", ["Lab manager"]))
    perms = list(
        Permission.objects.filter(code__in=["view_inventory", "view_requests"]).values_list(
            "pk", flat=True
        )
    )
    client.post(reverse("manage:role_add"), {"name": "Auditor", "permissions": perms})
    role = Role.objects.get(lab=lab, name="Auditor")
    assert set(role.permissions.values_list("code", flat=True)) == {
        "view_inventory",
        "view_requests",
    }

    only = Permission.objects.get(code="view_inventory")
    client.post(
        reverse("manage:role_edit", args=[role.pk]), {"name": "Auditor", "permissions": [only.pk]}
    )
    role.refresh_from_db()
    assert set(role.permissions.values_list("code", flat=True)) == {"view_inventory"}

    client.post(reverse("manage:role_delete", args=[role.pk]))
    assert not Role.objects.filter(pk=role.pk).exists()
