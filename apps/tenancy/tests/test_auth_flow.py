"""Login/logout flow: the app must never strand users on Django's fallback auth pages."""

import pytest

from apps.tenancy.models import User


@pytest.mark.django_db
def test_logout_redirects_to_start_page(client):
    user = User.objects.create_user(username="", email="out@x.de", password="pw")
    client.force_login(user)
    resp = client.post("/accounts/logout/")
    # Without LOGOUT_REDIRECT_URL this renders Django's bare "Logged out" page (200)
    # whose login link points at the admin login — the app start page is the contract.
    assert resp.status_code == 302
    assert resp["Location"] == "/"
