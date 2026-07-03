"""Form for raising and editing a procurement request.

Related choices (vendor, budget, shipping address, tags) are scoped to the active lab.
Derived money fields (tax, total) and the whole workflow (status, approver, assignments)
are intentionally absent — those are computed or driven by the state machine, never typed.

Vendors and tags can be created on the fly: the page's combobox/tag widgets write the
typed names into ``new_vendor`` / ``new_tags`` hidden inputs, and the rows are only
created when the request itself saves (nothing is created for an abandoned form).
"""

from __future__ import annotations

from datetime import date, timedelta

from django import forms

from apps.attachments.forms import MAX_SIZE_MB, MultipleFileField
from apps.attachments.models import Attachment
from apps.inventory.forms import hazard_statement_field
from apps.inventory.models import Tag
from apps.tenancy.models import Lab

from .models import CURRENCIES, Budget, Request, ShippingAddress, Vendor

_INPUT_CLASS = (
    "w-full rounded border border-gray-300 px-3 py-2 text-sm "
    "focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
)


class RequestForm(forms.ModelForm):
    new_vendor = forms.CharField(required=False, max_length=200, widget=forms.HiddenInput)
    attachments = MultipleFileField(
        required=False,
        label="Attachments",
        help_text=f"PO, quote, SDS, manual … (PDF, images, office docs; {MAX_SIZE_MB} MB each)",
    )

    class Meta:
        model = Request
        fields = [
            "item_name",
            "catalog_number",
            "cas_number",
            "product_url",
            "signal_word",
            "storage_class",
            "hazards",
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
            # Explicit ISO format: <input type="date"> only accepts yyyy-mm-dd.
            "expected_delivery": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "comment": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"product_url": "Product URL", "cas_number": "CAS number"}

    def __init__(self, *args, lab: Lab, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lab = lab
        # Bind the lab up front so save(commit=True) and per-lab lookups both see it.
        self.instance.lab = lab
        self.fields["vendor"].queryset = Vendor.objects.filter(lab=lab).order_by("name")
        self.fields["budget"].queryset = Budget.objects.filter(lab=lab).order_by("number")
        self.fields["shipping_address"].queryset = ShippingAddress.objects.filter(lab=lab).order_by(
            "label"
        )
        self.fields["tags"].queryset = Tag.objects.filter(lab=lab).order_by("name")
        self.fields["hazards"] = hazard_statement_field()

        # Currency is a fixed dropdown; keep an off-list code (imported data) selectable.
        codes = list(CURRENCIES)
        for extra in (self.instance.currency if self.instance.pk else "", lab.default_currency):
            if extra and extra not in codes:
                codes.append(extra)
        self.fields["currency"] = forms.ChoiceField(
            choices=[(code, code) for code in codes], label="Currency"
        )

        # self.initial (built from the model instance) beats field.initial, so lab-level
        # defaults for a new request must be written there.
        if not self.instance.pk:
            self.initial["currency"] = lab.default_currency or "EUR"
            # Standard lead time; the template offers +3d/+2wks/… shortcuts to adjust.
            self.initial["expected_delivery"] = date.today() + timedelta(weeks=1)
            for field_name, model in (("shipping_address", ShippingAddress), ("budget", Budget)):
                default = model.default_for(lab)
                if default is not None:
                    self.initial[field_name] = default

        self.fields["vendor"].widget.attrs.update(
            {"data-combobox": "", "data-combobox-create": "new_vendor"}
        )
        self.fields["budget"].widget.attrs["data-combobox"] = ""
        self.fields["shipping_address"].widget.attrs["data-combobox"] = ""
        self.fields["tags"].widget.attrs["data-tags"] = ""
        self.fields["attachments"].widget.attrs["class"] = (
            "block w-full text-sm text-gray-600 file:mr-3 file:rounded file:border-0 "
            "file:bg-gray-100 file:px-3 file:py-1.5 file:text-sm file:font-medium "
            "file:text-gray-700 hover:file:bg-gray-200"
        )
        self.fields["unit_price"].widget.attrs.update({"min": "0", "step": "0.01"})
        self.fields["shipping_cost"].widget.attrs.update({"min": "0", "step": "0.01"})
        self.fields["pack_count"].widget.attrs["min"] = "1"

        for field in self.fields.values():
            if isinstance(field.widget, forms.SelectMultiple):
                field.widget.attrs.setdefault("class", _INPUT_CLASS + " h-28")
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
        """Store files uploaded with the form as attachments on the saved request."""
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

    def save(self, commit: bool = True) -> Request:
        instance = super().save(commit=False)
        vendor_name = self.cleaned_data.get("new_vendor", "").strip()
        if vendor_name and instance.vendor is None:
            instance.vendor, _ = Vendor.objects.get_or_create(lab=self.lab, name=vendor_name)
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    def _save_m2m(self) -> None:
        super()._save_m2m()
        for name in self.cleaned_data.get("new_tags", []):
            tag, _ = Tag.objects.get_or_create(lab=self.lab, name=name)
            self.instance.tags.add(tag)
