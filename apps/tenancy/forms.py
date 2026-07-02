"""Personal (non-admin) forms for tenancy — profile and notification preferences."""

from __future__ import annotations

from django import forms

from .models import Membership, User

_INPUT = (
    "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm "
    "focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
)
_SELECT = _INPUT


class ProfileForm(forms.ModelForm):
    """A user's own account details. The friendly name is display-only, not an identifier."""

    class Meta:
        model = User
        fields = ["friendly_name"]
        labels = {"friendly_name": "Friendly name"}
        help_texts = {
            "friendly_name": "Shown instead of your email in lists and tables. "
            "Leave blank to show your email.",
        }
        widgets = {
            "friendly_name": forms.TextInput(
                attrs={"class": _INPUT, "placeholder": "e.g. Jane Doe"}
            ),
        }


class NotificationSettingsForm(forms.ModelForm):
    """A member's per-lab email preferences, showing only the categories they can act on."""

    class Meta:
        model = Membership
        fields = ["approval_notifications", "request_update_notifications"]
        labels = {
            "approval_notifications": "When a request needs approval",
            "request_update_notifications": "When one of my requests changes status",
        }
        help_texts = {
            "approval_notifications": "How you hear about requests waiting for your approval.",
            "request_update_notifications": "Updates to requests you raised or are ordering.",
        }

    def __init__(self, *args, can_approve: bool, can_request: bool, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not can_approve:
            self.fields.pop("approval_notifications")
        if not can_request:
            self.fields.pop("request_update_notifications")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", _SELECT)
