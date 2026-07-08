"""Forms for the lab-admin screens (all gated behind ``manage_lab``).

Every form takes the active ``lab`` so related choices stay tenant-scoped and so the
list/form CRUD views can construct them uniformly.
"""

from __future__ import annotations

from decimal import Decimal

from django import forms

from apps.inventory.models import FieldDefinition, FieldPreset, Location
from apps.procurement.models import (
    CURRENCIES,
    Budget,
    ShippingAddress,
    Vendor,
    normalize_vendor_name,
)

from .models import Lab, Permission, Role, User

_INPUT = (
    "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm "
    "focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
)


def _style(form: forms.BaseForm) -> None:
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput | forms.CheckboxSelectMultiple):
            continue
        css = _INPUT + (" h-24" if isinstance(widget, forms.Textarea) else "")
        widget.attrs.setdefault("class", css)


class _LabForm(forms.ModelForm):
    """ModelForm that accepts (and ignores unless needed) the active lab."""

    def __init__(self, *args, lab: Lab, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lab = lab
        # Bind the lab up front so per-lab uniqueness checks and save() both see it.
        self.instance.lab = lab
        self._scope(lab)
        _style(self)

    def _scope(self, lab: Lab) -> None:  # overridden where FK choices need scoping
        pass

    def _get_validation_exclusions(self) -> set[str]:
        # ``lab`` isn't a form field, so ModelForm excludes it and silently skips every
        # per-lab unique constraint — duplicates then crash on the DB constraint at
        # save(). ``lab`` is bound in __init__, so keep it in the validation and the
        # constraints surface as form errors instead.
        exclude = super()._get_validation_exclusions()
        exclude.discard("lab")
        return exclude


class VendorForm(_LabForm):
    class Meta:
        model = Vendor
        fields = ["name", "country"]
        help_texts = {
            "country": "ISO code, e.g. DE, FR, US. Determines the EU/non-EU signal for "
            "the central-purchasing suggestion; leave blank if unknown (no signal)."
        }

    def clean_name(self) -> str:
        # Whitespace variants of one supplier shouldn't become separate rows.
        return normalize_vendor_name(self.cleaned_data["name"])

    def clean_country(self) -> str:
        country = (self.cleaned_data.get("country") or "").strip().upper()
        if country and (len(country) != 2 or not country.isalpha()):
            raise forms.ValidationError("Use a two-letter ISO country code, e.g. DE or US.")
        return country


class ShippingAddressForm(_LabForm):
    class Meta:
        model = ShippingAddress
        fields = ["label", "address", "is_default"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}
        help_texts = {
            "is_default": "Preselected on new requests. Only one address can be the default."
        }


class BudgetForm(_LabForm):
    class Meta:
        model = Budget
        fields = ["number", "name", "owner", "is_default"]
        help_texts = {
            "is_default": "Preselected on new requests. Only one budget can be the default."
        }

    def _scope(self, lab: Lab) -> None:
        self.fields["owner"].queryset = User.objects.filter(memberships__lab=lab).distinct()
        self.fields["owner"].required = False


class LocationForm(_LabForm):
    class Meta:
        model = Location
        fields = ["name", "parent", "room_number"]
        help_texts = {
            "parent": "Where this location sits, e.g. the room a fridge is in. "
            "Leave empty for a top-level location.",
            "room_number": "Optional room number, matched during imports.",
        }

    def _scope(self, lab: Lab) -> None:
        parent = self.fields["parent"]
        parent.queryset = Location.objects.filter(lab=lab)
        # Depth-first full-path labels; when editing, hide the location's own subtree
        # so it can't be moved inside itself.
        excluded = set(Location.subtree_pks(lab, self.instance.pk)) if self.instance.pk else set()
        parent.choices = [
            ("", parent.empty_label),
            *(
                (location.pk, location.full_path)
                for location in Location.tree_for_lab(lab)
                if location.pk not in excluded
            ),
        ]

    def clean_parent(self) -> Location | None:
        parent = self.cleaned_data["parent"]
        # Backstop for the choice filtering above: reject any cycle-creating move.
        if (
            parent
            and self.instance.pk
            and parent.pk in Location.subtree_pks(self.lab, self.instance.pk)
        ):
            raise forms.ValidationError("A location cannot be placed inside itself.")
        return parent


class FieldDefinitionForm(_LabForm):
    class Meta:
        model = FieldDefinition
        fields = ["key", "label", "data_type"]
        help_texts = {"key": "Short identifier stored on items; cannot be changed later."}

    def _scope(self, lab: Lab) -> None:
        # The key is the JSON key on every item that uses it, so freeze it after creation.
        if self.instance.pk:
            self.fields["key"].disabled = True

    def clean_key(self) -> str:
        return self.cleaned_data["key"].strip().lower().replace(" ", "_")


class FieldPresetForm(_LabForm):
    class Meta:
        model = FieldPreset
        fields = ["name", "fields"]
        widgets = {
            "fields": forms.CheckboxSelectMultiple(
                attrs={"class": "mr-1.5 h-4 w-4 rounded border-gray-300 text-teal-600"}
            )
        }
        help_texts = {
            "fields": "Applying the preset on an item form reveals these fields in one click."
        }

    def _scope(self, lab: Lab) -> None:
        field = self.fields["fields"]
        field.queryset = FieldDefinition.objects.filter(lab=lab).order_by("label")
        field.label_from_instance = lambda definition: f"{definition.label} ({definition.key})"


class LabSettingsForm(forms.ModelForm):
    class Meta:
        model = Lab
        fields = [
            "name",
            "default_vat_rate",
            "default_currency",
            "central_purchasing_threshold_net",
            "po_deviation_threshold_pct",
        ]
        widgets = {"default_currency": forms.Select(choices=[(c, c) for c in CURRENCIES])}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["default_vat_rate"].help_text = "Fraction, e.g. 0.19 for 19% VAT."
        self.fields["default_currency"].help_text = "Preselected on new requests."
        self.fields["central_purchasing_threshold_net"].help_text = (
            "Net total above which central purchasing is suggested. "
            "Leave blank to use the instance default."
        )
        self.fields["po_deviation_threshold_pct"].help_text = (
            "Price drift (%) above which recreating the order form is suggested. "
            "Leave blank to use the instance default."
        )
        _style(self)

    def clean_default_vat_rate(self) -> Decimal:
        rate = self.cleaned_data["default_vat_rate"]
        if rate < 0 or rate > 1:
            raise forms.ValidationError("VAT rate must be between 0 and 1.")
        return rate


def _lab_roles(lab: Lab):
    return Role.objects.filter(lab=lab, is_template=False).order_by("name")


class MemberAddForm(forms.Form):
    """Add (or re-invite) a member by email and assign their lab roles."""

    email = forms.EmailField()
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.none(), required=False, widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, lab: Lab, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lab = lab
        self.fields["roles"].queryset = _lab_roles(lab)
        self.fields["roles"].label_from_instance = lambda role: role.name
        self.fields["email"].widget.attrs.setdefault("class", _INPUT)

    def clean_email(self) -> str:
        # Preserve the typed casing for readability; uniqueness and lookups are
        # case-insensitive (see User.Meta constraint and get_or_create_by_email).
        return self.cleaned_data["email"].strip()


class MemberRolesForm(forms.Form):
    """Edit the roles on an existing membership."""

    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.none(), required=False, widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, lab: Lab, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["roles"].queryset = _lab_roles(lab)
        self.fields["roles"].label_from_instance = lambda role: role.name


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ["name", "permissions"]
        widgets = {"permissions": forms.CheckboxSelectMultiple}

    def __init__(self, *args, lab: Lab, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lab = lab
        self.instance.lab = lab  # bind lab for the (lab, name) uniqueness check + save
        self.fields["permissions"].queryset = Permission.objects.all()
        self.fields["permissions"].label_from_instance = lambda perm: perm.label
        self.fields["name"].widget.attrs.setdefault("class", _INPUT)
