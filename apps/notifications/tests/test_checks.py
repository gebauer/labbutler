import pytest

from apps.notifications.checks import check_base_url


@pytest.mark.parametrize("url", ["", "labbutler.example.org", "/", "ftp://x.org"])
def test_missing_or_relative_base_url_is_an_error_in_production(settings, url):
    settings.DEBUG = False
    settings.LABBUTLER_BASE_URL = url
    assert [error.id for error in check_base_url()] == ["labbutler.E001"]


@pytest.mark.parametrize("url", ["https://labbutler.example.org", "http://10.0.0.5:8000/"])
def test_absolute_base_url_passes(settings, url):
    settings.DEBUG = False
    settings.LABBUTLER_BASE_URL = url
    assert check_base_url() == []


def test_debug_does_not_require_a_base_url(settings):
    settings.DEBUG = True
    settings.LABBUTLER_BASE_URL = ""
    assert check_base_url() == []
