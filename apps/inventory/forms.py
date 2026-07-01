"""Forms for inventory item create/edit.

Querysets for related fields (location, vendor, owner, tags) are scoped to the active
lab so a form can never reference another tenant's rows. The human ID and legacy serial
are intentionally absent: the ID is frozen at creation and never edited here.
"""

from __future__ import annotations

from django import forms

from apps.procurement.models import Vendor
from apps.tenancy.models import Lab, User

from .models import FieldDefinition, Item, Location, Tag

_INPUT_CLASS = (
    "w-full rounded border border-gray-300 px-3 py-2 text-sm "
    "focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
)

# Prefix that marks a dynamically-added custom-field form field.
_CUSTOM_PREFIX = "cf_"


def _custom_field(definition: FieldDefinition) -> forms.Field:
    """Build the right (optional) form field for a lab custom-field definition."""
    label = definition.label
    if definition.data_type == FieldDefinition.DataType.NUMBER:
        return forms.DecimalField(label=label, required=False)
    if definition.data_type == FieldDefinition.DataType.DATE:
        return forms.DateField(
            label=label, required=False, widget=forms.DateInput(attrs={"type": "date"})
        )
    if definition.data_type == FieldDefinition.DataType.BOOLEAN:
        return forms.BooleanField(label=label, required=False)
    return forms.CharField(label=label, required=False)


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

        # One input per lab custom-field definition, pre-filled from the item's values.
        self.custom_definitions = list(
            FieldDefinition.objects.filter(lab=lab).order_by("label")
        )
        stored = self.instance.custom_fields or {}
        for definition in self.custom_definitions:
            field = _custom_field(definition)
            field.initial = stored.get(definition.key)
            self.fields[f"{_CUSTOM_PREFIX}{definition.key}"] = field

        for field in self.fields.values():
            if isinstance(field.widget, forms.SelectMultiple):
                field.widget.attrs.setdefault("class", _INPUT_CLASS + " h-32")
            elif isinstance(field.widget, forms.CheckboxInput):
                continue
            else:
                field.widget.attrs.setdefault("class", _INPUT_CLASS)

    @staticmethod
    def _serialize(definition: FieldDefinition, value: object) -> object:
        """Turn a cleaned custom-field value into something JSON-storable."""
        if definition.data_type == FieldDefinition.DataType.DATE:
            return value.isoformat()
        if definition.data_type == FieldDefinition.DataType.NUMBER:
            return float(value)
        if definition.data_type == FieldDefinition.DataType.BOOLEAN:
            return True
        return str(value)

    def save(self, commit: bool = True) -> Item:
        item = super().save(commit=False)
        values = dict(item.custom_fields or {})
        for definition in self.custom_definitions:
            raw = self.cleaned_data.get(f"{_CUSTOM_PREFIX}{definition.key}")
            if raw in (None, "") or raw is False:
                values.pop(definition.key, None)  # cleared / unchecked -> drop the key
            else:
                values[definition.key] = self._serialize(definition, raw)
        item.custom_fields = values
        if commit:
            item.save()
            self.save_m2m()
        return item

    def core_fields(self) -> list:
        """Bound fields for the model's own columns (for template grouping)."""
        return [f for f in self if not f.name.startswith(_CUSTOM_PREFIX)]

    def custom_fields_bound(self) -> list:
        """Bound fields for the lab custom-field pool."""
        return [f for f in self if f.name.startswith(_CUSTOM_PREFIX)]
