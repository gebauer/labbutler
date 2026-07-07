"""Personal account views: onboarding, notification preferences, superuser impersonation."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEntry

from .catalog import ALL_PERMISSION_CODES, PERMISSION_CATALOG
from .forms import NotificationSettingsForm, ProfileForm
from .middleware import SESSION_KEY
from .models import Membership, Permission, User
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


class FirstLoginView(LoginView):
    """Standard login, except a user's very first sign-in lands on the welcome tour.

    Any ``next`` destination is carried along so the tour's continue button still
    reaches the page the user originally asked for.
    """

    def get_success_url(self) -> str:
        target = super().get_success_url()
        if self.request.user.onboarding_seen_at is None:
            return reverse("tenancy:onboarding") + "?" + urlencode({"next": target})
        return target


@login_required
def onboarding(request: HttpRequest) -> HttpResponse:
    """Short welcome tour, shown automatically on the first sign-in.

    Rendering the page stamps ``onboarding_seen_at`` so the login redirect fires only
    once; the page stays reachable under /welcome/ for re-reading. While impersonating,
    the stamp is skipped so "View as" never consumes someone else's first-visit tour.
    """
    user = request.user
    if user.onboarding_seen_at is None and getattr(request, "impersonator", None) is None:
        user.onboarding_seen_at = timezone.now()
        user.save(update_fields=["onboarding_seen_at"])
    next_url = request.GET.get("next", "")
    if not next_url or not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = "/"
    return render(
        request,
        "tenancy/onboarding.html",
        {"lab": get_current_lab(request), "next_url": next_url},
    )


@login_required
def account_settings(request: HttpRequest) -> HttpResponse:
    """Personal settings for the active lab: the account's friendly name plus per-lab
    email preferences.

    The notification section shows the procurement categories the member can act on
    (approval settings for approvers, request-update settings for people who can raise
    requests) and the weekly expiry report, which every member can tune.
    """
    lab = get_current_lab(request)
    if lab is None:
        return render(request, "inventory/no_lab.html", status=403)

    membership = Membership.objects.filter(user=request.user, lab=lab).first()
    can_approve = request.user.can(lab, "approve_request")
    can_request = request.user.can(lab, "create_request")
    can_view_inventory = request.user.can(lab, "view_inventory")

    profile_form = ProfileForm(request.POST or None, instance=request.user)
    notif_form = (
        NotificationSettingsForm(
            request.POST or None,
            instance=membership,
            can_approve=can_approve,
            can_request=can_request,
            can_view_inventory=can_view_inventory,
        )
        if membership is not None
        else None
    )

    forms = [f for f in (profile_form, notif_form) if f is not None]
    # Validate every form (list, not generator) so each renders its own errors on failure.
    if request.method == "POST" and all([f.is_valid() for f in forms]):
        for form in forms:
            form.save()
        messages.success(request, "Settings saved.")
        return redirect("tenancy:settings")

    return render(
        request,
        "tenancy/settings.html",
        {
            "lab": lab,
            "profile_form": profile_form,
            "notif_form": notif_form,
            "effective_permissions": _effective_permissions(request.user, lab),
            "role_names": (
                list(membership.roles.values_list("name", flat=True)) if membership else []
            ),
        },
    )


def _effective_permissions(user: User, lab) -> list[dict]:
    """The full permission catalog with whether ``user`` holds each code in ``lab``.

    Resolved as a set in one query (rather than ``user.can`` per code) and returned in
    catalog order, so the settings page can render a stable granted/not-granted list.
    """
    if user.is_superuser:
        held = set(ALL_PERMISSION_CODES)
    else:
        held = set(
            Permission.objects.filter(
                roles__memberships__user=user, roles__memberships__lab=lab
            ).values_list("code", flat=True)
        )
    return [
        {"code": code, "label": label, "held": code in held} for code, label in PERMISSION_CATALOG
    ]


def _record_impersonation(request: HttpRequest, action: str, target: User) -> None:
    """Audit an impersonation start/stop against the active lab (if any)."""
    lab = get_current_lab(request)
    if lab is not None:
        AuditEntry.record(
            lab=lab,
            actor=_real_user(request),
            action=action,
            target=target,
            changes={"target": target.email},
        )


@login_required
@require_POST
def impersonate(request: HttpRequest) -> HttpResponse:
    """Start (or switch) viewing the app as another user — superusers only."""
    if not settings.LABBUTLER_IMPERSONATION_ENABLED or not _real_user(request).is_superuser:
        raise PermissionDenied
    target = User.objects.filter(pk=request.POST.get("user") or 0).first()
    if target is None or target.pk == _real_user(request).pk:
        request.session.pop(SESSION_KEY, None)  # self / invalid -> just stop
    else:
        request.session[SESSION_KEY] = target.pk
        _record_impersonation(request, "tenancy.impersonation_started", target)
        messages.info(request, f"Now viewing as {target.email}.")
    return redirect(_safe_next(request))


@login_required
@require_POST
def stop_impersonating(request: HttpRequest) -> HttpResponse:
    request.session.pop(SESSION_KEY, None)
    if getattr(request, "impersonator", None) is not None:
        _record_impersonation(request, "tenancy.impersonation_stopped", request.user)
    return redirect(_safe_next(request))
