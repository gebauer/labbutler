"""Expose the app version, its GitHub release link and the docs URL to every template."""

from django.conf import settings
from django.http import HttpRequest

from . import version


def version_info(request: HttpRequest) -> dict:
    return {
        "app_version": version.git_tag,
        "app_release_url": version.release_url,
        "app_commit": version.commit,
        "app_commit_url": version.commit_url,
        "docs_url": settings.DOCS_URL,
    }
