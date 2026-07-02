"""Superuser impersonation — "View as another user" for testing roles.

When a superuser has picked someone to view as (``impersonate_id`` in the session), swap
``request.user`` to that person for the rest of the request so the whole app — nav,
dashboard, permission checks — renders exactly as they would see it. The real superuser is
kept on ``request.impersonator`` for the banner and the "return to yourself" action.

Fail-safe: the swap only happens when the *real* logged-in user is a superuser, so a
lingering session key can never escalate a normal account. The whole feature is also
gated on ``LABBUTLER_IMPERSONATION_ENABLED`` — a deployment opts in explicitly.

While impersonating, the real superuser is published in :data:`current_impersonator` for
the duration of the request, so audit writes deep in service code can record who
genuinely acted (see :meth:`apps.audit.models.AuditEntry.record`).
"""

from __future__ import annotations

from contextvars import ContextVar

from django.conf import settings

from .models import User

SESSION_KEY = "impersonate_id"

# The real logged-in superuser for the current request, or None when not impersonating.
current_impersonator: ContextVar[User | None] = ContextVar("current_impersonator", default=None)


class ImpersonationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = None
        if settings.LABBUTLER_IMPERSONATION_ENABLED:
            target_id = request.session.get(SESSION_KEY)
            user = getattr(request, "user", None)
            if target_id and user is not None and user.is_authenticated and user.is_superuser:
                target = User.objects.filter(pk=target_id).first()
                if target is not None:
                    request.impersonator = user
                    request.user = target
                    token = current_impersonator.set(user)
        try:
            return self.get_response(request)
        finally:
            if token is not None:
                current_impersonator.reset(token)
