"""Forms for inventory item create/edit.

Querysets for related fields (location, vendor, owner, tags) are scoped to the active
lab so a form can never reference another tenant's rows. The human ID and legacy serial
are intentionally absent: the ID is frozen at creation and never edited here.
"""

from __future__ import annotations

from django import forms
from django.db.models import Case, IntegerField, Value, When
from django.templatetags.static import static

from apps.procurement.models import Vendor
from apps.tenancy.models import Lab, User

from . import ghs, ids
from .models import FieldDefinition, HazardStatement, Item, Location, Tag

_INPUT_CLASS = (
    "w-full rounded border border-gray-300 px-3 py-2 text-sm "
    "focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
)

# Prefix that marks a dynamically-added custom-field form field.
_CUSTOM_PREFIX = "cf_"

# Model fields rendered in a dedicated "Hazards (GHS)" template section, not the
# core-fields grid.
HAZARD_FIELDS = ("signal_word", "hazards")


class HazardStatementMultipleChoiceField(forms.ModelMultipleChoiceField):
    """Multi-select over the global GHS catalog, labelled ``code — official text``."""

    def label_from_instance(self, obj: HazardStatement) -> str:
        return f"{obj.code} — {obj.text_en}" if obj.text_en else obj.code


class HazardSelect(forms.SelectMultiple):
    """SelectMultiple that tags each option with its GHS pictogram codes.

    The JS picker unions ``data-pictograms`` over the selected options to show the
    pictograms the current selection implies — icons appear/disappear with the codes.
    """

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        pictograms = ghs.pictograms_for(str(value))
        if pictograms:
            option["attrs"]["data-pictograms"] = " ".join(pictograms)
        return option


def hazard_statement_field() -> HazardStatementMultipleChoiceField:
    """The shared hazard picker used by both the item and the request form.

    All ~300 catalog entries are rendered as options; the ``data-hazards`` widget is
    progressively enhanced into a typeahead pill picker (static/js/forms.js), and
    degrades to a native multi-select without JS.
    """
    queryset = HazardStatement.objects.annotate(
        kind_order=Case(
            When(kind=HazardStatement.Kind.H, then=Value(0)),
            When(kind=HazardStatement.Kind.EUH, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )
    ).order_by("kind_order", "code")
    return HazardStatementMultipleChoiceField(
        queryset=queryset,
        required=False,
        label="GHS hazard statements",
        help_text="H-, EUH- and P-statements. Type to search by code or text.",
        widget=HazardSelect(attrs={"data-hazards": "", "data-icon-base": static("img/ghs/")}),
    )


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
            "hazards",
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
        # Depth-first order with full paths so nested locations read unambiguously
        # ("Room 376 / Fridge A / Shelf 2"); the queryset above still validates the pick.
        self.fields["location"].choices = [
            ("", self.fields["location"].empty_label),
            *((location.pk, location.full_path) for location in Location.tree_for_lab(lab)),
        ]
        self.fields["vendor"].queryset = Vendor.objects.filter(lab=lab)
        self.fields["tags"].queryset = Tag.objects.filter(lab=lab)
        self.fields["owner"].queryset = User.objects.filter(memberships__lab=lab).distinct()
        self.fields["hazards"] = hazard_statement_field()

        # New items get a chosen ID (from the preprinted pool); existing IDs are frozen.
        self.creating = self.instance.pk is None
        if self.creating:
            self.id_suggestions = ids.suggest_ids(lab, 10)
            self.fields["human_id"] = forms.CharField(
                label="Item ID",
                required=False,
                help_text="Open the ▾ to pick a free ID, or type your own.",
                # Left empty on purpose: a prefilled value makes the browser filter the
                # datalist down to that one match, so the dropdown would look empty.
                widget=forms.TextInput(
                    attrs={
                        "list": "id-options",
                        "autocomplete": "off",
                        "placeholder": self.id_suggestions[0],
                    }
                ),
            )

        # One input per lab custom-field definition, pre-filled from the item's values.
        self.custom_definitions = list(FieldDefinition.objects.filter(lab=lab).order_by("label"))
        stored = self.instance.custom_fields or {}
        for definition in self.custom_definitions:
            field = _custom_field(definition)
            field.initial = stored.get(definition.key)
            self.fields[f"{_CUSTOM_PREFIX}{definition.key}"] = field

        if self.creating:
            self.order_fields(["human_id", *[f for f in self.fields if f != "human_id"]])

        for field in self.fields.values():
            if isinstance(field.widget, forms.SelectMultiple):
                field.widget.attrs.setdefault("class", _INPUT_CLASS + " h-32")
            elif isinstance(field.widget, forms.CheckboxInput):
                continue
            else:
                field.widget.attrs.setdefault("class", _INPUT_CLASS)

    def clean_human_id(self) -> str:
        raw = (self.cleaned_data.get("human_id") or "").strip()
        if not raw:
            return ""  # save() falls back to the next free ID
        try:
            human_id = ids.normalize_item_id(self.lab, raw)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
        if ids.item_id_taken(self.lab, human_id):
            raise forms.ValidationError(f"{human_id} is already in use.")
        return human_id

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
        if self.creating:
            item.human_id = self.cleaned_data.get("human_id") or ids.suggest_ids(self.lab, 1)[0]
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
        return [
            f for f in self if not f.name.startswith(_CUSTOM_PREFIX) and f.name not in HAZARD_FIELDS
        ]

    def hazard_fields(self) -> list:
        """Bound fields for the dedicated hazards section."""
        return [self[name] for name in HAZARD_FIELDS]

    def custom_fields_bound(self) -> list:
        """Bound fields for the lab custom-field pool."""
        return [f for f in self if f.name.startswith(_CUSTOM_PREFIX)]
