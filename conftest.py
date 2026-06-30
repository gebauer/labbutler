"""Project-wide pytest fixtures.

Tests render real templates, which reference hashed static files via ``{% static %}``.
The production ``ManifestStaticFilesStorage`` requires a ``collectstatic`` manifest that
isn't built for the test run, so swap in the plain storage backend (it just joins
STATIC_URL + path) for every test.
"""

import pytest


@pytest.fixture(autouse=True)
def _plain_static_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
