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


_CHECKBOX = (
    "h-4 w-4 rounded border-gray-300 text-teal-600 "
    "focus:outline-none focus:ring-1 focus:ring-teal-500"
)


class NotificationSettingsForm(forms.ModelForm):
    """A member's per-lab email preferences, showing only the categories they can act on.

    The expiry-report settings are available to every member; the owned-only toggle is
    hidden for members without ``view_inventory``, whose reports are always limited to
    their own items anyway (fail closed on lab-wide data).
    """

    class Meta:
        model = Membership
        fields = [
            "approval_notifications",
            "request_update_notifications",
            "expiry_notifications",
            "expiry_owned_only",
            "expiry_days_ahead",
        ]
        labels = {
            "approval_notifications": "When a request needs approval",
            "request_update_notifications": "When one of my requests changes status",
            "expiry_notifications": "Weekly expiry report",
            "expiry_owned_only": "Only include items I own",
            "expiry_days_ahead": "Warn about upcoming expiry",
        }
        help_texts = {
            "approval_notifications": "How you hear about requests waiting for your approval.",
            "request_update_notifications": "Updates to requests you raised or are ordering.",
            "expiry_notifications": "The weekly email about expired items — everything still "
            "expired, only what expired since the last report, or no email at all.",
            "expiry_owned_only": "Limit the report to items where you are set as the owner.",
            "expiry_days_ahead": "How far ahead the report warns you about items expiring soon.",
        }
        widgets = {
            "expiry_owned_only": forms.CheckboxInput(attrs={"class": _CHECKBOX}),
        }

    def __init__(
        self, *args, can_approve: bool, can_request: bool, can_view_inventory: bool, **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        if not can_approve:
            self.fields.pop("approval_notifications")
        if not can_request:
            self.fields.pop("request_update_notifications")
        if not can_view_inventory:
            self.fields.pop("expiry_owned_only")
        for name, field in self.fields.items():
            if name != "expiry_owned_only":
                field.widget.attrs.setdefault("class", _SELECT)
