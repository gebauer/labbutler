"""First-login onboarding: the welcome tour shows exactly once, right after sign-in."""

import pytest
from django.urls import reverse

from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab

LOGIN_URL = "/accounts/login/"
URL = reverse("tenancy:onboarding")


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


def _member(lab, email="new@x.de", roles=("Member",)) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=list(roles))
    return user


def _login(client, email):
    return client.post(LOGIN_URL, {"username": email, "password": "pw"})


@pytest.mark.django_db
def test_first_login_redirects_to_welcome_tour(client, lab):
    _member(lab)
    resp = _login(client, "new@x.de")
    assert resp.status_code == 302
    assert resp.url == f"{URL}?next=%2F"


@pytest.mark.django_db
def test_first_login_carries_next_destination_along(client, lab):
    _member(lab)
    inventory = reverse("inventory:item_list")
    resp = client.post(f"{LOGIN_URL}?next={inventory}", {"username": "new@x.de", "password": "pw"})
    assert resp.status_code == 302
    assert resp.url == f"{URL}?next={inventory.replace('/', '%2F')}"
    # The tour's continue button points at the originally requested page.
    assert f'href="{inventory}"'.encode() in client.get(resp.url).content


@pytest.mark.django_db
def test_tour_renders_and_marks_seen_so_next_login_goes_home(client, lab):
    user = _member(lab)
    _login(client, "new@x.de")

    resp = client.get(URL)
    assert resp.status_code == 200
    assert b"Welcome to LabButler" in resp.content
    user.refresh_from_db()
    assert user.onboarding_seen_at is not None

    client.post("/accounts/logout/")
    resp = _login(client, "new@x.de")
    assert resp.status_code == 302
    assert resp.url == "/"


@pytest.mark.django_db
def test_offsite_next_falls_back_to_home(client, lab):
    client.force_login(_member(lab))
    resp = client.get(URL, {"next": "https://evil.example/"})
    assert resp.status_code == 200
    assert b'href="https://evil.example/"' not in resp.content


@pytest.mark.django_db
def test_tour_requires_login(client, lab):
    resp = client.get(URL)
    assert resp.status_code == 302
    assert resp.url.startswith(LOGIN_URL)


@pytest.mark.django_db
def test_impersonation_does_not_consume_the_targets_tour(client, lab, settings):
    settings.LABBUTLER_IMPERSONATION_ENABLED = True
    su = User.objects.create_superuser(username="", email="su@x.de", password="pw")
    target = _member(lab, "fresh@x.de")
    client.force_login(su)
    client.post(reverse("tenancy:impersonate"), {"user": target.pk})

    assert client.get(URL).status_code == 200
    target.refresh_from_db()
    assert target.onboarding_seen_at is None
