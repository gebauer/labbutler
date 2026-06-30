"""Forms for inventory item create/edit.

Querysets for related fields (location, vendor, owner, tags) are scoped to the active
lab so a form can never reference another tenant's rows. The human ID and legacy serial
are intentionally absent: the ID is frozen at creation and never edited here.
"""

from __future__ import annotations

from django import forms

from apps.procurement.models import Vendor
from apps.tenancy.models import Lab, User

from .models import Item, Location, Tag

_INPUT_CLASS = (
    "w-full rounded border border-gray-300 px-3 py-2 text-sm "
    "focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
)


class ItemForm(forms.ModelForm):
    """Edit the editable, structured fields of an :class:`Item`."""

    class Meta:
        model = Item
        fields = [
            "name",
            "location",
            "vendor",
            "owner",
            "barcode",
            "catalog_number",
            "cas_number",
            "lot_number",
            "price_amount",
            "price_currency",
            "expiration_date",
            "signal_word",
            "wgk",
            "storage_class",
            "tags",
        ]
        widgets = {
            "expiration_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, lab: Lab, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lab = lab
        self.fields["location"].queryset = Location.objects.filter(lab=lab)
        self.fields["vendor"].queryset = Vendor.objects.filter(lab=lab)
        self.fields["tags"].queryset = Tag.objects.filter(lab=lab)
        self.fields["owner"].queryset = User.objects.filter(memberships__lab=lab).distinct()

        for field in self.fields.values():
            if isinstance(field.widget, forms.SelectMultiple):
                field.widget.attrs.setdefault("class", _INPUT_CLASS + " h-32")
            elif isinstance(field.widget, forms.CheckboxInput):
                continue
            else:
                field.widget.attrs.setdefault("class", _INPUT_CLASS)
