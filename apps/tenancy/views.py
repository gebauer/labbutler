"""Superuser impersonation endpoints (start / stop "View as another user")."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .middleware import SESSION_KEY
from .models import User


def _real_user(request: HttpRequest):
    """The genuinely logged-in account, even mid-impersonation."""
    return getattr(request, "impersonator", None) or request.user


def _safe_next(request: HttpRequest) -> str:
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return "/"


@login_required
@require_POST
def impersonate(request: HttpRequest) -> HttpResponse:
    """Start (or switch) viewing the app as another user — superusers only."""
    if not _real_user(request).is_superuser:
        raise PermissionDenied
    target = User.objects.filter(pk=request.POST.get("user") or 0).first()
    if target is None or target.pk == _real_user(request).pk:
        request.session.pop(SESSION_KEY, None)  # self / invalid -> just stop
    else:
        request.session[SESSION_KEY] = target.pk
        messages.info(request, f"Now viewing as {target.email}.")
    return redirect(_safe_next(request))


@login_required
@require_POST
def stop_impersonating(request: HttpRequest) -> HttpResponse:
    request.session.pop(SESSION_KEY, None)
    return redirect(_safe_next(request))
