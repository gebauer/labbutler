"""Login/logout flow: the app must never strand users on Django's fallback auth pages."""

import pytest

from apps.tenancy.models import User


@pytest.mark.django_db
def test_password_reset_email_is_multipart_with_working_text_part(client, mailoutbox):
    User.objects.create_user(username="", email="ada@x.de", password="pw")
    resp = client.post("/accounts/password_reset/", {"email": "ada@x.de"})
    assert resp.status_code == 302
    assert len(mailoutbox) == 1
    mail = mailoutbox[0]
    assert "reset" in mail.body and "/accounts/reset/" in mail.body
    assert mail.alternatives and mail.alternatives[0][1] == "text/html"
    assert "Choose a new password" in mail.alternatives[0][0]


@pytest.mark.django_db
def test_logout_redirects_to_start_page(client):
    user = User.objects.create_user(username="", email="out@x.de", password="pw")
    client.force_login(user)
    resp = client.post("/accounts/logout/")
    # Without LOGOUT_REDIRECT_URL this renders Django's bare "Logged out" page (200)
    # whose login link points at the admin login — the app start page is the contract.
    assert resp.status_code == 302
    assert resp["Location"] == "/"
