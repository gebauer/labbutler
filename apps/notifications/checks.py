"""Startup checks for email configuration."""

from __future__ import annotations

from urllib.parse import urlsplit

from django.conf import settings
from django.core.checks import Error, register


@register()
def check_base_url(app_configs=None, **kwargs) -> list[Error]:
    """Outside DEBUG, ``LABBUTLER_BASE_URL`` must be an absolute http(s) URL.

    Every link in an email is built from it; without it the invitation's set-password
    link is a bare path that no mail client can open, so a new member is locked out.
    An error (not a warning) so the misconfiguration stops `migrate` — and with it the
    container start — instead of surfacing as confused users.
    """
    if settings.DEBUG:
        return []
    parts = urlsplit(settings.LABBUTLER_BASE_URL or "")
    if parts.scheme in ("http", "https") and parts.netloc:
        return []
    return [
        Error(
            "LABBUTLER_BASE_URL must be the absolute public URL of this installation "
            f"(got {settings.LABBUTLER_BASE_URL!r}).",
            hint="Set it to e.g. https://labbutler.example.org — links in emails "
            "(invitations, password resets, notifications) are built from it.",
            id="labbutler.E001",
        )
    ]
