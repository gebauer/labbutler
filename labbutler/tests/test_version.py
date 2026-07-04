"""Version footer: version derived from pyproject.toml, release link in every page."""

import tomllib
from pathlib import Path

import pytest
from django.urls import reverse

from labbutler import version


def test_version_matches_pyproject():
    pyproject = Path(version.__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as fh:
        expected = tomllib.load(fh)["project"]["version"]
    assert version.__version__ == expected


def test_git_tag_uses_hyphenated_prerelease():
    # PEP 440 "1.0.0rc1" maps to the repo's tag scheme "v1.0.0-rc1".
    assert version.git_tag == "v" + version.__version__.replace("rc", "-rc")
    assert version.release_url.endswith(f"/releases/tag/{version.git_tag}")


@pytest.mark.django_db
def test_footer_links_to_release_page(client):
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    assert version.git_tag.encode() in resp.content
    assert version.release_url.encode() in resp.content
