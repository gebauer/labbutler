"""The privacy notice must be reachable without signing in and linked from every page."""


def test_privacy_page_is_public(client, db):
    response = client.get("/privacy/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Privacy notice" in content
    assert "PubChem" in content


def test_footer_links_to_privacy_notice(client, db):
    response = client.get("/accounts/login/")
    assert 'href="/privacy/"' in response.content.decode()


def test_privacy_page_names_every_product_lookup_vendor(client, db):
    from apps.procurement.product_lookup import supported_vendor_names

    content = client.get("/privacy/").content.decode()
    for vendor in supported_vendor_names():
        assert vendor in content


def test_privacy_page_states_login_record_retention(client, db, settings):
    settings.LABBUTLER_LOGIN_RECORD_RETENTION_DAYS = 42
    content = client.get("/privacy/").content.decode()
    assert "successful or failed" in content
    assert "after 42 days" in " ".join(content.split())


def test_privacy_page_shows_operator_contact_when_configured(client, db, settings):
    settings.LABBUTLER_PRIVACY_CONTACT = "AG Test — privacy@lab.test"
    assert "privacy@lab.test" in client.get("/privacy/").content.decode()
    settings.LABBUTLER_PRIVACY_CONTACT = ""
    assert "Contact for this installation" not in client.get("/privacy/").content.decode()
