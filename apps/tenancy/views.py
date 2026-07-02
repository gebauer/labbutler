"""Personal account views: notification preferences and superuser impersonation."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import NotificationSettingsForm
from .middleware import SESSION_KEY
from .models import Membership, User
from .scoping import get_current_lab


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
def notification_settings(request: HttpRequest) -> HttpResponse:
    """Let a member set their per-lab email preferences for the active lab.

    Only shows the categories the member can act on: approval settings for approvers,
    request-update settings for people who can raise requests.
    """
    lab = get_current_lab(request)
    if lab is None:
        return render(request, "inventory/no_lab.html", status=403)

    membership = Membership.objects.filter(user=request.user, lab=lab).first()
    can_approve = request.user.can(lab, "approve_request")
    can_request = request.user.can(lab, "create_request")

    # No membership (e.g. a superuser) or no relevant permission -> nothing to configure.
    if membership is None or not (can_approve or can_request):
        return render(request, "tenancy/notification_settings.html", {"lab": lab, "form": None})

    form = NotificationSettingsForm(
        request.POST or None,
        instance=membership,
        can_approve=can_approve,
        can_request=can_request,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Notification preferences saved.")
        return redirect("tenancy:notification_settings")

    return render(request, "tenancy/notification_settings.html", {"lab": lab, "form": form})


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
