"""Expose the active lab and the user's labs to every template (for the nav switcher)."""

from django.http import HttpRequest

from .scoping import get_current_lab, user_labs


def labs(request: HttpRequest) -> dict:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    available = list(user_labs(user))
    current = get_current_lab(request)
    return {
        "current_lab": current,
        "available_labs": available,
        "can_import": bool(current and user.can(current, "import_inventory")),
        "can_view_requests": bool(current and user.can(current, "view_requests")),
        "can_manage_lab": bool(current and user.can(current, "manage_lab")),
    }
