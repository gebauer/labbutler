"""Lab administration screens (the ``manage_lab`` area), so a lab can be run without the
Django admin.

The four lab-owned lists (suppliers, budgets, shipping addresses, custom fields) share
one registry-driven set of CRUD views; members, roles and settings have bespoke views.
Every view is gated on ``manage_lab`` and scoped to ``request.lab``.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.audit.models import AuditEntry
from apps.inventory.models import FieldDefinition
from apps.procurement.models import Budget, ShippingAddress, Vendor

from .manage_forms import (
    BudgetForm,
    FieldDefinitionForm,
    LabSettingsForm,
    ShippingAddressForm,
    VendorForm,
)
from .scoping import require_permission


@dataclass(frozen=True)
class CrudConfig:
    model: type
    form_class: type
    singular: str
    plural: str
    order_by: str


CRUD: dict[str, CrudConfig] = {
    "suppliers": CrudConfig(Vendor, VendorForm, "supplier", "Suppliers", "name"),
    "budgets": CrudConfig(Budget, BudgetForm, "budget", "Budgets", "number"),
    "addresses": CrudConfig(
        ShippingAddress, ShippingAddressForm, "shipping address", "Shipping addresses", "label"
    ),
    "fields": CrudConfig(
        FieldDefinition, FieldDefinitionForm, "custom field", "Custom fields", "label"
    ),
}


def _config(kind: str) -> CrudConfig:
    config = CRUD.get(kind)
    if config is None:
        raise Http404("Unknown admin section")
    return config


@require_permission("manage_lab")
def index(request: HttpRequest) -> HttpResponse:
    """Admin landing page with one card per manageable area."""
    sections = [
        (kind, cfg, cfg.model.objects.filter(lab=request.lab).count())
        for kind, cfg in CRUD.items()
    ]
    return render(request, "manage/index.html", {"sections": sections})


@require_permission("manage_lab")
def crud_list(request: HttpRequest, kind: str) -> HttpResponse:
    config = _config(kind)
    objects = config.model.objects.filter(lab=request.lab).order_by(config.order_by)
    return render(request, "manage/list.html", {"kind": kind, "config": config, "objects": objects})


@require_permission("manage_lab")
def crud_form(request: HttpRequest, kind: str, pk: int | None = None) -> HttpResponse:
    config = _config(kind)
    instance = get_object_or_404(config.model, pk=pk, lab=request.lab) if pk else None

    if request.method == "POST":
        form = config.form_class(request.POST, instance=instance, lab=request.lab)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.lab = request.lab
            obj.save()
            form.save_m2m()
            AuditEntry.record(
                lab=request.lab,
                actor=request.user,
                action=f"lab.{kind}_{'updated' if instance else 'created'}",
                target=obj,
                changes={"name": str(obj)},
            )
            messages.success(request, f"Saved {config.singular} “{obj}”.")
            return redirect("manage:list", kind=kind)
    else:
        form = config.form_class(instance=instance, lab=request.lab)

    return render(
        request,
        "manage/form.html",
        {"kind": kind, "config": config, "form": form, "instance": instance},
    )


@require_permission("manage_lab")
def crud_delete(request: HttpRequest, kind: str, pk: int) -> HttpResponse:
    config = _config(kind)
    obj = get_object_or_404(config.model, pk=pk, lab=request.lab)
    if request.method == "POST":
        label = str(obj)
        AuditEntry.record(
            lab=request.lab,
            actor=request.user,
            action=f"lab.{kind}_deleted",
            target=(config.model.__name__, obj.pk),
            changes={"name": label},
        )
        obj.delete()
        messages.success(request, f"Deleted {config.singular} “{label}”.")
        return redirect("manage:list", kind=kind)
    return render(
        request,
        "manage/confirm_delete.html",
        {"kind": kind, "config": config, "object": obj},
    )


@require_permission("manage_lab")
def settings(request: HttpRequest) -> HttpResponse:
    lab = request.lab
    if request.method == "POST":
        form = LabSettingsForm(request.POST, instance=lab)
        if form.is_valid():
            form.save()
            AuditEntry.record(
                lab=lab,
                actor=request.user,
                action="lab.settings_updated",
                target=lab,
                changes={"fields": sorted(form.changed_data)},
            )
            messages.success(request, "Lab settings saved.")
            return redirect("manage:settings")
    else:
        form = LabSettingsForm(instance=lab)
    return render(request, "manage/settings.html", {"form": form, "lab": lab})
