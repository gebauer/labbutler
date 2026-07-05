"""Lab administration screens (the ``manage_lab`` area), so a lab can be run without the
Django admin.

The lab-owned lists (locations, suppliers, budgets, shipping addresses, custom fields,
field presets) share one registry-driven set of CRUD views; members, roles and settings
have bespoke views.
Every view is gated on ``manage_lab`` and scoped to ``request.lab``.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEntry
from apps.inventory.models import FieldDefinition, FieldPreset, Location
from apps.procurement.models import Budget, ShippingAddress, Vendor
from apps.procurement.services import find_duplicate_vendors, merge_vendors

from .manage_forms import (
    BudgetForm,
    FieldDefinitionForm,
    FieldPresetForm,
    LabSettingsForm,
    LocationForm,
    MemberAddForm,
    MemberRolesForm,
    RoleForm,
    ShippingAddressForm,
    VendorForm,
)
from .models import Membership, Role, User
from .scoping import require_permission


@dataclass(frozen=True)
class CrudConfig:
    model: type
    form_class: type
    singular: str
    plural: str
    order_by: str


CRUD: dict[str, CrudConfig] = {
    "locations": CrudConfig(Location, LocationForm, "location", "Locations", "name"),
    "suppliers": CrudConfig(Vendor, VendorForm, "supplier", "Suppliers", "name"),
    "budgets": CrudConfig(Budget, BudgetForm, "budget", "Budgets", "number"),
    "addresses": CrudConfig(
        ShippingAddress, ShippingAddressForm, "shipping address", "Shipping addresses", "label"
    ),
    "fields": CrudConfig(
        FieldDefinition, FieldDefinitionForm, "custom field", "Custom fields", "label"
    ),
    "presets": CrudConfig(FieldPreset, FieldPresetForm, "field preset", "Field presets", "name"),
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
        (kind, cfg, cfg.model.objects.filter(lab=request.lab).count()) for kind, cfg in CRUD.items()
    ]
    return render(request, "manage/index.html", {"sections": sections})


@require_permission("manage_lab")
def crud_list(request: HttpRequest, kind: str) -> HttpResponse:
    config = _config(kind)
    if config.model is Location:
        # Depth-first order with cached full paths, so the list reads as a tree.
        objects = Location.tree_for_lab(request.lab)
    else:
        objects = config.model.objects.filter(lab=request.lab).order_by(config.order_by)
    context = {"kind": kind, "config": config, "objects": objects}
    if config.model is Vendor:
        context["duplicate_group_count"] = len(find_duplicate_vendors(request.lab))
    return render(request, "manage/list.html", context)


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
    delete_warning = ""
    if config.model is Location:
        nested = len(Location.subtree_pks(request.lab, obj.pk)) - 1
        if nested:
            delete_warning = (
                f"This also deletes {nested} nested location{'s' if nested != 1 else ''}. "
                "Items stored anywhere inside lose their location but are kept."
            )
    return render(
        request,
        "manage/confirm_delete.html",
        {"kind": kind, "config": config, "object": obj, "delete_warning": delete_warning},
    )


# --- Suppliers: merge duplicates ---------------------------------------------------


def _annotated_vendors(lab):
    # distinct=True: the double reverse-FK join would otherwise multiply the counts.
    return Vendor.objects.filter(lab=lab).annotate(
        request_count=Count("requests", distinct=True),
        item_count=Count("items", distinct=True),
    )


def _selected_vendors(request: HttpRequest, raw_ids: list[str]) -> list[Vendor]:
    """Resolve submitted vendor ids against the current lab; unknown/foreign ids 404."""
    try:
        pks = {int(raw) for raw in raw_ids}
    except ValueError:
        raise Http404("Invalid supplier selection") from None
    vendors = list(_annotated_vendors(request.lab).filter(pk__in=pks).order_by("name"))
    if len(vendors) != len(pks):
        raise Http404("Unknown supplier in selection")
    return vendors


@require_permission("manage_lab")
def supplier_merge(request: HttpRequest) -> HttpResponse:
    """Merge duplicate suppliers: pick vendors (GET), confirm winner and merge (POST)."""
    if request.method == "POST":
        selected = _selected_vendors(request, request.POST.getlist("vendors"))
        winner_pk = request.POST.get("winner", "")
        winner = next((v for v in selected if str(v.pk) == winner_pk), None)
        if len(selected) < 2 or winner is None:
            messages.error(request, "Select at least two suppliers and choose which one to keep.")
            return redirect("manage:supplier_merge")
        losers = [v for v in selected if v.pk != winner.pk]
        try:
            merge_vendors(
                lab=request.lab,
                winner=winner,
                losers=losers,
                actor=request.user,
                new_name=request.POST.get("new_name", ""),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("manage:supplier_merge")
        moved = sum(v.request_count for v in losers), sum(v.item_count for v in losers)
        messages.success(
            request,
            f"Merged {len(losers)} supplier{'s' if len(losers) != 1 else ''} into "
            f"“{winner.name}” ({moved[0]} requests, {moved[1]} items moved).",
        )
        return redirect("manage:list", kind="suppliers")

    selected = _selected_vendors(request, request.GET.getlist("vendors"))
    if len(selected) >= 2:
        # Confirm step: default winner is the most-used vendor (oldest on a tie).
        default_winner = max(selected, key=lambda v: (v.request_count + v.item_count, -v.pk))
        return render(
            request,
            "manage/merge_suppliers.html",
            {"mode": "confirm", "selected": selected, "default_winner": default_winner},
        )

    return render(
        request,
        "manage/merge_suppliers.html",
        {
            "mode": "select",
            "vendors": _annotated_vendors(request.lab).order_by("name"),
            "duplicate_groups": find_duplicate_vendors(request.lab),
        },
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


# --- Members ---------------------------------------------------------------------------


@require_permission("manage_lab")
def members(request: HttpRequest) -> HttpResponse:
    memberships = (
        Membership.objects.filter(lab=request.lab)
        .select_related("user")
        .prefetch_related("roles")
        .order_by("user__email")
    )
    query = request.GET.get("q", "").strip()
    if query:
        # Match on the identity (email) or the display label (friendly name).
        memberships = memberships.filter(
            Q(user__email__icontains=query) | Q(user__friendly_name__icontains=query)
        )
    return render(
        request,
        "manage/members.html",
        {
            "memberships": memberships,
            "add_form": MemberAddForm(lab=request.lab),
            "query": query,
        },
    )


@require_permission("manage_lab")
@require_POST
def member_add(request: HttpRequest) -> HttpResponse:
    form = MemberAddForm(request.POST, lab=request.lab)
    if not form.is_valid():
        messages.error(request, "Enter a valid email address.")
        return redirect("manage:members")

    email = form.cleaned_data["email"]
    user, user_created = User.objects.get_or_create_by_email(email, defaults={"username": email})
    membership, created = Membership.objects.get_or_create(user=user, lab=request.lab)
    membership.roles.set(form.cleaned_data["roles"])
    if user_created:
        # Brand-new account: welcome them and hand over a set-password link. Existing users
        # added to another lab already have credentials, so they get nothing here.
        from apps.notifications.tasks import send_welcome_email

        lab_pk = request.lab.pk
        transaction.on_commit(lambda: send_welcome_email.delay(user.pk, lab_pk))
    AuditEntry.record(
        lab=request.lab,
        actor=request.user,
        action="lab.member_added" if created else "lab.member_updated",
        target=membership,
        changes={"email": email, "roles": [r.name for r in form.cleaned_data["roles"]]},
    )
    messages.success(request, f"{'Added' if created else 'Updated'} {email}.")
    return redirect("manage:members")


@require_permission("manage_lab")
def member_edit(request: HttpRequest, pk: int) -> HttpResponse:
    membership = get_object_or_404(
        Membership.objects.select_related("user"), pk=pk, lab=request.lab
    )
    if request.method == "POST":
        form = MemberRolesForm(request.POST, lab=request.lab)
        if form.is_valid():
            membership.roles.set(form.cleaned_data["roles"])
            AuditEntry.record(
                lab=request.lab,
                actor=request.user,
                action="lab.member_updated",
                target=membership,
                changes={"roles": [r.name for r in form.cleaned_data["roles"]]},
            )
            messages.success(request, f"Updated {membership.user.email}.")
            return redirect("manage:members")
    else:
        form = MemberRolesForm(lab=request.lab, initial={"roles": membership.roles.all()})
    return render(request, "manage/member_form.html", {"form": form, "membership": membership})


@require_permission("manage_lab")
@require_POST
def member_remove(request: HttpRequest, pk: int) -> HttpResponse:
    membership = get_object_or_404(Membership, pk=pk, lab=request.lab)
    if membership.user_id == request.user.pk:
        messages.error(request, "You can't remove yourself from the lab.")
        return redirect("manage:members")
    email = membership.user.email
    AuditEntry.record(
        lab=request.lab,
        actor=request.user,
        action="lab.member_removed",
        target=("Membership", membership.pk),
        changes={"email": email},
    )
    membership.delete()
    messages.success(request, f"Removed {email}.")
    return redirect("manage:members")


# --- Roles -----------------------------------------------------------------------------


@require_permission("manage_lab")
def role_list(request: HttpRequest) -> HttpResponse:
    roles = (
        Role.objects.filter(lab=request.lab, is_template=False)
        .prefetch_related("permissions")
        .order_by("name")
    )
    return render(request, "manage/roles.html", {"roles": roles})


@require_permission("manage_lab")
def role_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    instance = get_object_or_404(Role, pk=pk, lab=request.lab, is_template=False) if pk else None
    if request.method == "POST":
        form = RoleForm(request.POST, instance=instance, lab=request.lab)
        if form.is_valid():
            role = form.save()
            AuditEntry.record(
                lab=request.lab,
                actor=request.user,
                action="lab.role_updated" if instance else "lab.role_created",
                target=role,
                changes={"name": role.name},
            )
            messages.success(request, f"Saved role “{role.name}”.")
            return redirect("manage:roles")
    else:
        form = RoleForm(instance=instance, lab=request.lab)
    return render(request, "manage/role_form.html", {"form": form, "role": instance})


@require_permission("manage_lab")
@require_POST
def role_delete(request: HttpRequest, pk: int) -> HttpResponse:
    role = get_object_or_404(Role, pk=pk, lab=request.lab, is_template=False)
    name = role.name
    AuditEntry.record(
        lab=request.lab,
        actor=request.user,
        action="lab.role_deleted",
        target=("Role", role.pk),
        changes={"name": name},
    )
    role.delete()
    messages.success(request, f"Deleted role “{name}”.")
    return redirect("manage:roles")
