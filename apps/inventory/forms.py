"""Forms for inventory item create/edit.

Querysets for related fields (location, vendor, owner, tags) are scoped to the active
lab so a form can never reference another tenant's rows. The human ID and legacy serial
are intentionally absent: the ID is frozen at creation and never edited here.

Vendors and tags can be created on the fly: the page's combobox/tag widgets write the
typed names into ``new_vendor`` / ``new_tags`` hidden inputs, and the rows are only
created when the item itself saves (nothing is created for an abandoned form). Files
uploaded with the form are stored as attachments on the saved item.
"""

from __future__ import annotations

from django import forms
from django.db.models import Case, IntegerField, Value, When
from django.templatetags.static import static

from apps.attachments.forms import MAX_SIZE_MB, MultipleFileField
from apps.attachments.models import Attachment
from apps.procurement.models import Vendor
from apps.tenancy.models import Lab, User

from . import ghs, ids, labels
from .models import FieldDefinition, FieldPreset, HazardStatement, Item, Location, Tag

_INPUT_CLASS = (
    "w-full rounded border border-gray-300 px-3 py-2 text-sm "
    "focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
)

# Prefix that marks a dynamically-added custom-field form field.
_CUSTOM_PREFIX = "cf_"


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

    new_vendor = forms.CharField(required=False, max_length=200, widget=forms.HiddenInput)
    attachments = MultipleFileField(
        required=False,
        label="Attachments",
        help_text=f"SDS, CoA, manual … (PDF, images, office docs; {MAX_SIZE_MB} MB each)",
    )

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
            "product_url",
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
        labels = {"product_url": "Product URL"}

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

        self.fields["vendor"].widget.attrs.update(
            {"data-combobox": "", "data-combobox-create": "new_vendor"}
        )
        self.fields["location"].widget.attrs["data-combobox"] = ""
        self.fields["owner"].widget.attrs["data-combobox"] = ""
        self.fields["tags"].widget.attrs["data-tags"] = ""
        self.fields["attachments"].widget.attrs["class"] = (
            "block w-full text-sm text-gray-600 file:mr-3 file:rounded file:border-0 "
            "file:bg-gray-100 file:px-3 file:py-1.5 file:text-sm file:font-medium "
            "file:text-gray-700 hover:file:bg-gray-200"
        )

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

        # Named field bundles: (preset, [cf_ input names]) for the progressive-disclosure
        # UI on the item form (empty fields start collapsed; a preset reveals its bundle).
        self.presets: list[tuple[FieldPreset, list[str]]] = []
        if self.custom_definitions:
            input_names = {d.pk: f"{_CUSTOM_PREFIX}{d.key}" for d in self.custom_definitions}
            self.presets = [
                (preset, [input_names[fd.pk] for fd in preset.fields.all() if fd.pk in input_names])
                for preset in FieldPreset.objects.filter(lab=lab)
                .prefetch_related("fields")
                .order_by("name")
            ]

        for field in self.fields.values():
            if isinstance(field.widget, forms.SelectMultiple):
                field.widget.attrs.setdefault("class", _INPUT_CLASS + " h-32")
            elif isinstance(field.widget, forms.CheckboxInput | forms.HiddenInput):
                continue
            else:
                field.widget.attrs.setdefault("class", _INPUT_CLASS)

    def clean(self) -> dict:
        cleaned = super().clean()
        if hasattr(self.data, "getlist"):
            raw_names = self.data.getlist("new_tags")
        else:  # plain-dict data (tests)
            raw_names = self.data.get("new_tags") or []
        new_tags = []
        for raw_name in raw_names:
            name = raw_name.strip()
            if not name:
                continue
            if len(name) > 100:
                self.add_error(None, f"Tag “{name[:40]}…” is too long (max 100 characters).")
            elif name.casefold() not in {tag.casefold() for tag in new_tags}:
                new_tags.append(name)
        cleaned["new_tags"] = new_tags
        return cleaned

    def save_attachments(self, *, user) -> None:
        """Store files uploaded with the form as attachments on the saved item."""
        for upload in self.cleaned_data.get("attachments", []):
            Attachment.objects.create(
                lab=self.lab,
                uploaded_by=user,
                target=self.instance,
                file=upload,
                original_name=upload.name,
                size=upload.size,
            )

    def new_tag_names(self) -> list[str]:
        """Pending on-the-fly tag names, so a re-rendered invalid form keeps them."""
        return getattr(self, "cleaned_data", {}).get("new_tags", [])

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
        vendor_name = self.cleaned_data.get("new_vendor", "").strip()
        if vendor_name and item.vendor is None:
            item.vendor, _ = Vendor.objects.get_or_create(lab=self.lab, name=vendor_name)
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

    def _save_m2m(self) -> None:
        super()._save_m2m()
        for name in self.cleaned_data.get("new_tags", []):
            tag, _ = Tag.objects.get_or_create(lab=self.lab, name=name)
            self.instance.tags.add(tag)

    def custom_fields_bound(self) -> list:
        """Bound fields for the lab custom-field pool."""
        return [f for f in self if f.name.startswith(_CUSTOM_PREFIX)]

    def revealed_custom_names(self) -> list[str]:
        """cf_ inputs the user revealed client-side, echoed so an invalid re-render
        keeps them open (same round-trip pattern as ``new_tags``)."""
        if not self.is_bound:
            return []
        if hasattr(self.data, "getlist"):
            raw = self.data.getlist("cf_revealed")
        else:  # plain-dict data (tests)
            raw = self.data.get("cf_revealed") or []
        return sorted(
            name for name in set(raw) if name.startswith(_CUSTOM_PREFIX) and name in self.fields
        )

    def custom_fields_meta(self) -> list[dict]:
        """Each cf_ bound field plus whether it must stay visible: it holds a value,
        has an error, or was revealed before an invalid submit."""
        revealed = set(self.revealed_custom_names())
        entries = []
        for bound in self.custom_fields_bound():
            value = bound.value()
            filled = (
                bool(bound.errors)
                or bound.name in revealed
                or not (value in (None, "") or value is False)
            )
            entries.append({"field": bound, "filled": filled})
        return entries


class LabelSheetForm(forms.Form):
    """Parameters for a preprinted Data Matrix label sheet (Avery 25.4 x 10 mm).

    The start row/column let a partially used sheet be fed again, continuing at
    the first free label. Bounds come from the sheet geometry in ``labels.py``.
    """

    start_id = forms.CharField(
        label="First ID",
        help_text="Labels count up from here, e.g. AGB-305.",
        widget=forms.TextInput(attrs={"class": _INPUT_CLASS}),
    )
    count = forms.IntegerField(
        label="Number of labels",
        min_value=1,
        max_value=10 * labels.AVERY_25X10_R.per_page,
        initial=labels.AVERY_25X10_R.per_page,
        widget=forms.NumberInput(attrs={"class": _INPUT_CLASS}),
    )
    start_row = forms.IntegerField(
        label="Start at row",
        min_value=1,
        max_value=labels.AVERY_25X10_R.rows,
        initial=1,
        widget=forms.NumberInput(attrs={"class": _INPUT_CLASS}),
    )
    start_column = forms.IntegerField(
        label="Start at column",
        min_value=1,
        max_value=labels.AVERY_25X10_R.columns,
        initial=1,
        widget=forms.NumberInput(attrs={"class": _INPUT_CLASS}),
    )

    def __init__(self, *args, lab: Lab, **kwargs):
        super().__init__(*args, **kwargs)
        self.lab = lab
        self.fields["start_id"].initial = ids.suggest_ids(lab, 1)[0]

    def clean_start_id(self) -> str:
        try:
            return ids.normalize_item_id(self.lab, self.cleaned_data["start_id"])
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error
