"""Form for raising and editing a procurement request.

Related choices (vendor, budget, shipping address, tags) are scoped to the active lab.
Derived money fields (tax, total) and the whole workflow (status, approver, assignments)
are intentionally absent — those are computed or driven by the state machine, never typed.
"""

from __future__ import annotations

from django import forms

from apps.inventory.models import Tag
from apps.tenancy.models import Lab

from .models import Budget, Request, ShippingAddress, Vendor

_INPUT_CLASS = (
    "w-full rounded border border-gray-300 px-3 py-2 text-sm "
    "focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
)


class RequestForm(forms.ModelForm):
    class Meta:
        model = Request
        fields = [
            "item_name",
            "catalog_number",
            "cas_number",
            "product_url",
            "vendor",
            "budget",
            "shipping_address",
            "unit_price",
            "currency",
            "pack_count",
            "shipping_cost",
            "includes_taxes",
            "is_urgent",
            "expected_delivery",
            "quote_id",
            "comment",
            "tags",
        ]
        widgets = {
            "expected_delivery": forms.DateInput(attrs={"type": "date"}),
            "comment": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, lab: Lab, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lab = lab
        self.fields["vendor"].queryset = Vendor.objects.filter(lab=lab)
        self.fields["budget"].queryset = Budget.objects.filter(lab=lab)
        self.fields["shipping_address"].queryset = ShippingAddress.objects.filter(lab=lab)
        self.fields["tags"].queryset = Tag.objects.filter(lab=lab)

        for field in self.fields.values():
            if isinstance(field.widget, forms.SelectMultiple):
                field.widget.attrs.setdefault("class", _INPUT_CLASS + " h-28")
            elif isinstance(field.widget, forms.CheckboxInput):
                continue
            else:
                field.widget.attrs.setdefault("class", _INPUT_CLASS)
