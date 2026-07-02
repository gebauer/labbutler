"""Login brute-force protection (django-axes)."""

import pytest
from django.urls import reverse

from apps.tenancy.models import User


@pytest.mark.django_db
def test_login_succeeds_with_axes_enabled(client, settings):
    settings.AXES_ENABLED = True
    User.objects.create_user(username="", email="ok@x.de", password="rightpass")
    resp = client.post(reverse("login"), {"username": "ok@x.de", "password": "rightpass"})
    assert resp.status_code == 302  # authenticated + redirected (axes didn't get in the way)


@pytest.mark.django_db
def test_login_is_case_insensitive_on_email(client, settings):
    settings.AXES_ENABLED = True
    User.objects.create_user(username="", email="Alice@x.de", password="rightpass")
    # Registered with mixed case; logging in with a different case still authenticates.
    resp = client.post(reverse("login"), {"username": "alice@x.de", "password": "rightpass"})
    assert resp.status_code == 302


@pytest.mark.django_db
def test_lockout_counter_is_shared_across_email_casings(client, settings):
    settings.AXES_ENABLED = True  # AXES_FAILURE_LIMIT defaults to 5
    User.objects.create_user(username="", email="Target@x.de", password="rightpass")
    login = reverse("login")

    # Alternate the casing on every failed attempt; a per-casing counter would never
    # reach the limit, so a lockout proves the counter is normalised to one key.
    statuses = []
    for i in range(7):
        username = "TARGET@x.de" if i % 2 else "target@x.de"
        statuses.append(client.post(login, {"username": username, "password": "wrong"}).status_code)
    assert 429 in statuses


@pytest.mark.django_db
def test_login_locks_out_after_repeated_failures(client, settings):
    settings.AXES_ENABLED = True  # AXES_FAILURE_LIMIT defaults to 5
    User.objects.create_user(username="", email="target@x.de", password="rightpass")
    login = reverse("login")
    bad = {"username": "target@x.de", "password": "wrong"}

    statuses = [client.post(login, bad).status_code for _ in range(7)]
    assert 429 in statuses  # repeated wrong-password guesses get locked out

    # Guessing stays blocked (with the lockout page) once locked.
    again = client.post(login, bad)
    assert again.status_code == 429
    assert b"Too many failed sign-in attempts" in again.content
