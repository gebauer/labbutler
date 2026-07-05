from django.db import connection
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

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
                {"widgets": dashboard.build(request.user, lab), "today": timezone.localdate()},
            )
    return render(request, "home.html")


def privacy(request: HttpRequest) -> HttpResponse:
    """Static privacy notice, publicly reachable so it can be read before signing in."""
    return render(request, "privacy.html")
