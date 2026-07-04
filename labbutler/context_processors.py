"""Expose the app version and its GitHub release link to every template (for the footer)."""

from django.http import HttpRequest

from . import version


def version_info(request: HttpRequest) -> dict:
    return {
        "app_version": version.git_tag,
        "app_release_url": version.release_url,
    }
