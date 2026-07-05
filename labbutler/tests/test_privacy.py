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
