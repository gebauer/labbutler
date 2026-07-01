"""Expose the active lab and the user's labs to every template (for the nav switcher)."""

from django.http import HttpRequest

from .models import User
from .scoping import get_current_lab, user_labs


def labs(request: HttpRequest) -> dict:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    available = list(user_labs(user))
    current = get_current_lab(request)
    context = {
        "current_lab": current,
        "available_labs": available,
        "can_import": bool(current and user.can(current, "import_inventory")),
        "can_view_requests": bool(current and user.can(current, "view_requests")),
        "can_manage_lab": bool(current and user.can(current, "manage_lab")),
    }

    # Impersonation controls, driven by the *real* logged-in user (a superuser).
    real = getattr(request, "impersonator", None) or user
    if real.is_superuser:
        members = User.objects.none()
        if current is not None:
            members = (
                User.objects.filter(memberships__lab=current)
                .exclude(pk=real.pk)
                .distinct()
                .order_by("email")
            )
        context["can_impersonate"] = True
        context["impersonating"] = getattr(request, "impersonator", None) is not None
        context["lab_members"] = members
    return context
