"""Inventory screens: a searchable item list plus detail, create, edit, and delete.

All views are gated by :func:`require_permission` and operate on ``request.lab`` only,
so a user only ever sees and edits items in a lab they belong to. List search is
HTMX-friendly: an HTMX request gets just the results partial back for live filtering.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEntry
from apps.tenancy.scoping import require_permission, set_current_lab, user_labs

from .forms import ItemForm
from .models import Item, Tag

PAGE_SIZE = 25

# Item columns searched by the free-text query box.
_SEARCH_FIELDS = (
    "name",
    "human_id",
    "legacy_serial",
    "barcode",
    "catalog_number",
    "cas_number",
    "lot_number",
)


def _filtered_items(lab, query: str, tag_id: str):
    """Return the lab's items narrowed by free-text query and optional tag."""
    items = (
        Item.objects.filter(lab=lab)
        .select_related("location", "vendor", "owner")
        .order_by("name", "human_id")
    )
    query = query.strip()
    if query:
        lookup = Q()
        for field_name in _SEARCH_FIELDS:
            lookup |= Q(**{f"{field_name}__icontains": query})
        items = items.filter(lookup)
    if tag_id:
        items = items.filter(tags__pk=tag_id)
    return items.distinct()


VIEW_MODES = ("table", "cards")
VIEW_SESSION_KEY = "inventory_view"


def _resolve_view_mode(request: HttpRequest) -> str:
    """Pick table/cards from the request, remembering the choice per session."""
    requested = request.GET.get("view")
    if requested in VIEW_MODES:
        request.session[VIEW_SESSION_KEY] = requested
        return requested
    return request.session.get(VIEW_SESSION_KEY, "table")


@require_permission("view_inventory")
def item_list(request: HttpRequest) -> HttpResponse:
    """Paginated, searchable item list, rendered as a table or cards. HTMX requests get
    only the results partial."""
    query = request.GET.get("q", "")
    tag_id = request.GET.get("tag", "")
    view_mode = _resolve_view_mode(request)
    items = _filtered_items(request.lab, query, tag_id)

    page = Paginator(items, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "query": query,
        "tag_id": tag_id,
        "view_mode": view_mode,
        "tags": Tag.objects.filter(lab=request.lab).order_by("name"),
        "can_manage": request.user.can(request.lab, "manage_inventory"),
    }
    if request.htmx:
        return render(request, "inventory/_item_results.html", context)
    return render(request, "inventory/item_list.html", context)


@require_permission("view_inventory")
def item_detail(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(
        Item.objects.select_related("location", "vendor", "owner").prefetch_related(
            "tags", "hazards"
        ),
        pk=pk,
        lab=request.lab,
    )
    return render(
        request,
        "inventory/item_detail.html",
        {
            "item": item,
            "custom_fields": _custom_field_rows(request.lab, item),
            "can_manage": request.user.can(request.lab, "manage_inventory"),
        },
    )


def _custom_field_rows(lab, item: Item) -> list[tuple[str, object]]:
    """Pair each stored custom-field value with its human label from the lab pool."""
    labels = dict(
        lab.field_definitions.values_list("key", "label")  # type: ignore[attr-defined]
    )
    return [(labels.get(key, key), value) for key, value in sorted(item.custom_fields.items())]


@require_permission("manage_inventory")
def item_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ItemForm(request.POST, lab=request.lab)
        if form.is_valid():
            item = form.save(commit=False)
            item.lab = request.lab
            item.human_id = request.lab.allocate_item_id()
            item.save()
            form.save_m2m()
            AuditEntry.record(
                lab=request.lab,
                actor=request.user,
                action="inventory.item_created",
                target=item,
                changes={"human_id": item.human_id, "name": item.name},
            )
            messages.success(request, f"Created {item.human_id}.")
            return redirect("inventory:item_detail", pk=item.pk)
    else:
        form = ItemForm(lab=request.lab)
    return render(
        request,
        "inventory/item_form.html",
        {"form": form, "title": "New item", "item": None},
    )


@require_permission("manage_inventory")
def item_edit(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(Item, pk=pk, lab=request.lab)
    if request.method == "POST":
        form = ItemForm(request.POST, instance=item, lab=request.lab)
        if form.is_valid():
            form.save()
            AuditEntry.record(
                lab=request.lab,
                actor=request.user,
                action="inventory.item_updated",
                target=item,
                changes={"fields": sorted(form.changed_data)},
            )
            messages.success(request, f"Saved {item.human_id}.")
            return redirect("inventory:item_detail", pk=item.pk)
    else:
        form = ItemForm(instance=item, lab=request.lab)
    return render(
        request,
        "inventory/item_form.html",
        {"form": form, "title": f"Edit {item.human_id}", "item": item},
    )


@require_permission("manage_inventory")
def item_delete(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(Item, pk=pk, lab=request.lab)
    if request.method == "POST":
        human_id = item.human_id
        AuditEntry.record(
            lab=request.lab,
            actor=request.user,
            action="inventory.item_deleted",
            target=("Item", item.pk),
            changes={"human_id": human_id, "name": item.name},
        )
        item.delete()
        messages.success(request, f"Deleted {human_id}.")
        return redirect("inventory:item_list")
    return render(request, "inventory/item_confirm_delete.html", {"item": item})


@login_required
@require_POST
def switch_lab(request: HttpRequest, slug: str) -> HttpResponse:
    """Set the session's active lab (must be one the user belongs to), then go to it."""
    lab = get_object_or_404(user_labs(request.user), slug=slug)
    set_current_lab(request, lab)
    return redirect(request.POST.get("next") or reverse("inventory:item_list"))
