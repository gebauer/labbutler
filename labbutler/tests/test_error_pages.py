"""Branded error pages, including those Django renders without request context."""

import pytest
from django.test import Client, RequestFactory
from django.views.defaults import server_error


@pytest.mark.django_db
def test_404_page_is_branded(client):
    resp = client.get("/no-such-page/")
    assert resp.status_code == 404
    assert "Page not found" in resp.content.decode()


@pytest.mark.django_db
def test_403_page_points_to_effective_permissions(client, django_user_model):
    from apps.tenancy.services import add_member, create_lab

    lab = create_lab(name="AG Err", item_id_prefix="ERR")
    user = django_user_model.objects.create_user(username="", email="v@x.de", password="pw")
    add_member(user=user, lab=lab, role_names=["Viewer"])
    client.force_login(user)

    resp = client.get("/manage/")
    assert resp.status_code == 403
    content = resp.content.decode()
    assert "access to this" in content and "Account settings" in content


def test_500_page_renders_without_any_context():
    resp = server_error(RequestFactory().get("/"))
    assert resp.status_code == 500
    assert "Something went wrong" in resp.content.decode()


@pytest.mark.django_db
def test_csrf_failure_explains_the_expired_form():
    resp = Client(enforce_csrf_checks=True).post("/accounts/login/", {"username": "x"})
    assert resp.status_code == 403
    assert "This form has expired" in resp.content.decode()
