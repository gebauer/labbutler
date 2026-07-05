"""Project-wide pytest fixtures.

Tests render real templates, which reference hashed static files via ``{% static %}``.
The production ``ManifestStaticFilesStorage`` requires a ``collectstatic`` manifest that
isn't built for the test run, so swap in the plain storage backend (it just joins
STATIC_URL + path) for every test.
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="also run tests marked slow (real LabSuit export commits)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip_slow = pytest.mark.skip(reason="needs --runslow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture(autouse=True)
def _fast_password_hasher(settings):
    """The default PBKDF2 hasher costs ~0.25s per hash and dominates test runtime;
    tests don't need secure hashes."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def _plain_static_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture(autouse=True)
def _disable_axes(settings):
    """Turn off login lockout by default so force_login-based tests are unaffected;
    the brute-force test re-enables it explicitly."""
    settings.AXES_ENABLED = False
