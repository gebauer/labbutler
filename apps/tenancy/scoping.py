"""Request-level lab scoping and permission enforcement for views.

Every screen in LabButler operates inside exactly one lab. These helpers resolve the
"current lab" from the session (falling back to the user's first membership) and gate
views on a permission code, so view code never reaches into memberships or roles
directly. The chosen lab is attached to ``request.lab`` for the wrapped view.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .models import Lab

SESSION_LAB_KEY = "current_lab_id"


def user_labs(user):
    """Labs the user may act in: their memberships, or every lab for a superuser."""
    if user.is_superuser:
        return Lab.objects.all().order_by("name")
    return Lab.objects.filter(memberships__user=user).order_by("name").distinct()


def get_current_lab(request: HttpRequest) -> Lab | None:
    """Resolve the active lab: the session selection if still valid, else the first."""
    labs = user_labs(request.user)
    selected = request.session.get(SESSION_LAB_KEY)
    if selected is not None:
        lab = labs.filter(pk=selected).first()
        if lab is not None:
            return lab
    return labs.first()


def set_current_lab(request: HttpRequest, lab: Lab) -> None:
    request.session[SESSION_LAB_KEY] = lab.pk


def require_permission(permission_code: str) -> Callable:
    """Wrap a view so it runs only for an authenticated member holding ``permission_code``.

    Resolves the current lab, attaches it to ``request.lab``, and fails closed: a user
    with no lab gets a friendly empty state; one lacking the permission gets a 403.
    """

    def decorator(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(view)
        @login_required
        def wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            lab = get_current_lab(request)
            if lab is None:
                return render(request, "inventory/no_lab.html", status=403)
            if not request.user.can(lab, permission_code):
                raise PermissionDenied
            request.lab = lab
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
