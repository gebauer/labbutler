"""Expose the active lab and the user's labs to every template (for the nav switcher)."""

from django.http import HttpRequest

from .scoping import get_current_lab, user_labs


def labs(request: HttpRequest) -> dict:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    available = list(user_labs(user))
    return {"current_lab": get_current_lab(request), "available_labs": available}
