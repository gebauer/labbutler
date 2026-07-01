"""Forms for the lab-admin screens (all gated behind ``manage_lab``).

Every form takes the active ``lab`` so related choices stay tenant-scoped and so the
list/form CRUD views can construct them uniformly.
"""

from __future__ import annotations

from decimal import Decimal

from django import forms

from apps.inventory.models import FieldDefinition
from apps.procurement.models import Budget, ShippingAddress, Vendor

from .models import Lab, User

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


class VendorForm(_LabForm):
    class Meta:
        model = Vendor
        fields = ["name"]


class ShippingAddressForm(_LabForm):
    class Meta:
        model = ShippingAddress
        fields = ["label", "address"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


class BudgetForm(_LabForm):
    class Meta:
        model = Budget
        fields = ["number", "name", "owner"]

    def _scope(self, lab: Lab) -> None:
        self.fields["owner"].queryset = User.objects.filter(memberships__lab=lab).distinct()
        self.fields["owner"].required = False


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


class LabSettingsForm(forms.ModelForm):
    class Meta:
        model = Lab
        fields = ["name", "default_vat_rate"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["default_vat_rate"].help_text = "Fraction, e.g. 0.19 for 19% VAT."
        _style(self)

    def clean_default_vat_rate(self) -> Decimal:
        rate = self.cleaned_data["default_vat_rate"]
        if rate < 0 or rate > 1:
            raise forms.ValidationError("VAT rate must be between 0 and 1.")
        return rate
