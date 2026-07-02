"""Project-level security hardening: response headers and settings behaviour."""

import importlib

import environ
import pytest
from django.core.exceptions import ImproperlyConfigured


def test_csp_header_is_sent_on_every_response(client, db):
    response = client.get("/accounts/login/")
    policy = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "script-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy


def test_missing_secret_key_fails_hard_outside_debug(monkeypatch):
    """Without DEBUG there is no insecure fallback key — startup must refuse."""
    monkeypatch.setenv("DJANGO_DEBUG", "false")
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    # Keep a developer's .env file from leaking a key back in during the reload.
    monkeypatch.setattr(environ.Env, "read_env", lambda *args, **kwargs: None)
    module = importlib.import_module("labbutler.settings")
    try:
        with pytest.raises(ImproperlyConfigured):
            importlib.reload(module)
    finally:
        # Restore the real env and re-execute the module so later imports see a
        # fully-initialised settings module again (django.conf is unaffected either way).
        monkeypatch.undo()
        importlib.reload(module)
