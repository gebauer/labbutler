"""Superuser 'View as' impersonation: effective-permission swap, gating, audit trail."""

import pytest
from django.urls import reverse

from apps.audit.models import AuditEntry
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab


@pytest.fixture(autouse=True)
def _impersonation_enabled(settings):
    """Enable the feature explicitly — its default follows DEBUG, which varies by host."""
    settings.LABBUTLER_IMPERSONATION_ENABLED = True


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


def _member(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


@pytest.mark.django_db
def test_impersonation_swaps_effective_permissions(client, lab):
    su = User.objects.create_superuser(username="", email="su@x.de", password="pw")
    viewer = _member(lab, "v@x.de", ["Viewer"])
    client.force_login(su)

    # As a superuser the admin area is reachable.
    assert client.get(reverse("manage:index")).status_code == 200

    resp = client.post(reverse("tenancy:impersonate"), {"user": viewer.pk})
    assert resp.status_code == 302

    # Now acting as the viewer: no manage_lab -> 403, and the banner shows.
    assert client.get(reverse("manage:index")).status_code == 403
    home = client.get(reverse("home"))
    assert b"Viewing as" in home.content and b"v@x.de" in home.content

    # Returning to yourself restores superuser access.
    client.post(reverse("tenancy:stop_impersonating"))
    assert client.get(reverse("manage:index")).status_code == 200


@pytest.mark.django_db
def test_non_superuser_cannot_impersonate(client, lab):
    member = _member(lab, "m@x.de", ["Member"])
    other = _member(lab, "o@x.de", ["Viewer"])
    client.force_login(member)
    assert client.post(reverse("tenancy:impersonate"), {"user": other.pk}).status_code == 403


@pytest.mark.django_db
def test_stale_session_key_does_not_escalate(client, lab):
    member = _member(lab, "m@x.de", ["Member"])
    victim = _member(lab, "boss@x.de", ["Lab manager"])
    client.force_login(member)
    # Even if a non-superuser somehow has the session key, the middleware ignores it.
    session = client.session
    session["impersonate_id"] = victim.pk
    session.save()
    assert client.get(reverse("manage:index")).status_code == 403  # still the member


@pytest.mark.django_db
def test_disabled_deployment_flag_turns_the_feature_off(client, lab, settings):
    settings.LABBUTLER_IMPERSONATION_ENABLED = False
    su = User.objects.create_superuser(username="", email="su@x.de", password="pw")
    viewer = _member(lab, "v@x.de", ["Viewer"])
    client.force_login(su)

    # No picker in the nav, and the endpoint refuses outright.
    assert b"View as" not in client.get(reverse("home")).content
    assert client.post(reverse("tenancy:impersonate"), {"user": viewer.pk}).status_code == 403

    # Even a lingering session key is ignored by the middleware.
    session = client.session
    session["impersonate_id"] = viewer.pk
    session.save()
    assert client.get(reverse("manage:index")).status_code == 200  # still the superuser


@pytest.mark.django_db
def test_actions_while_impersonating_keep_the_real_actor_on_record(client, lab):
    su = User.objects.create_superuser(username="", email="su@x.de", password="pw")
    manager = _member(lab, "boss@x.de", ["Lab manager"])
    client.force_login(su)

    client.post(reverse("tenancy:impersonate"), {"user": manager.pk})
    start = AuditEntry.objects.get(action="tenancy.impersonation_started")
    assert start.actor == su
    assert start.changes["target"] == "boss@x.de"

    # A state change made while impersonating is attributed to the impersonated user,
    # but the audit entry names the real superuser as well.
    client.post(reverse("manage:add", kwargs={"kind": "suppliers"}), {"name": "ACME"})
    entry = AuditEntry.objects.get(action="lab.suppliers_created")
    assert entry.actor == manager
    assert entry.changes["impersonated_by"] == "su@x.de"

    client.post(reverse("tenancy:stop_impersonating"))
    stop = AuditEntry.objects.get(action="tenancy.impersonation_stopped")
    assert stop.actor == su
    assert stop.changes["target"] == "boss@x.de"


@pytest.mark.django_db
def test_picker_offered_only_to_superusers(client, lab):
    su = User.objects.create_superuser(username="", email="su@x.de", password="pw")
    _member(lab, "v@x.de", ["Viewer"])
    client.force_login(su)
    assert b"View as" in client.get(reverse("home")).content

    member = _member(lab, "m@x.de", ["Member"])
    client.force_login(member)
    assert b"View as" not in client.get(reverse("home")).content
