"""Superuser impersonation — "View as another user" for testing roles.

When a superuser has picked someone to view as (``impersonate_id`` in the session), swap
``request.user`` to that person for the rest of the request so the whole app — nav,
dashboard, permission checks — renders exactly as they would see it. The real superuser is
kept on ``request.impersonator`` for the banner and the "return to yourself" action.

Fail-safe: the swap only happens when the *real* logged-in user is a superuser, so a
lingering session key can never escalate a normal account.
"""

from __future__ import annotations

from .models import User

SESSION_KEY = "impersonate_id"


class ImpersonationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        target_id = request.session.get(SESSION_KEY)
        user = getattr(request, "user", None)
        if target_id and user is not None and user.is_authenticated and user.is_superuser:
            target = User.objects.filter(pk=target_id).first()
            if target is not None:
                request.impersonator = user
                request.user = target
        return self.get_response(request)
