from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.procurement import product_lookup
from apps.tenancy import onboarding
from apps.tenancy.scoping import get_current_lab

from . import dashboard


def healthz(request: HttpRequest) -> HttpResponse:
    """Liveness/readiness probe: 200 only if the database is reachable."""
    connection.ensure_connection()
    return HttpResponse("ok", content_type="text/plain")


def home(request: HttpRequest) -> HttpResponse:
    """A role-aware dashboard for a logged-in member; the landing page otherwise."""
    if request.user.is_authenticated:
        lab = get_current_lab(request)
        if lab is not None:
            return render(
                request,
                "dashboard.html",
                {
                    "widgets": dashboard.build(request.user, lab),
                    "checklist": onboarding.checklist_for_dashboard(request.user, lab),
                    "today": timezone.localdate(),
                },
            )
    return render(request, "home.html")


def privacy(request: HttpRequest) -> HttpResponse:
    """Privacy notice, publicly reachable so it can be read before signing in.

    Facts that change with code or configuration (vendor list, retention, operator
    contact) are passed in rather than written into the template, so the notice can't
    drift from what the installation actually does.
    """
    context = {
        "controller_contact": settings.LABBUTLER_PRIVACY_CONTACT,
        "login_retention_days": settings.LABBUTLER_LOGIN_RECORD_RETENTION_DAYS,
        "lookup_vendors": product_lookup.supported_vendor_names(),
    }
    return render(request, "privacy.html", context)
