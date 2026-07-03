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
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from apps.attachments.models import Attachment
from apps.audit.models import AuditEntry
from apps.comments.models import Comment
from apps.procurement.models import Vendor
from apps.tenancy.models import User
from apps.tenancy.scoping import require_permission, set_current_lab, user_labs

from . import ghs
from . import ghs_lookup as ghs_lookup_client
from .forms import ItemForm
from .models import HazardStatement, Item, Location, Tag

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

# Query param -> the item field it filters on. Tag filters by name (a type-in combobox
# offers the lab's tags, which are too many to show as pills); the rest match by pk.
_FACETS = {
    "tag": "tags__name__icontains",
    "location": "location__pk",
    "owner": "owner__pk",
    "vendor": "vendor__pk",
}


def _filtered_items(lab, query: str, facets: dict[str, str]):
    """Return the lab's items narrowed by free-text query and any active facet filters."""
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
    for param, lookup_field in _FACETS.items():
        value = facets.get(param)
        if value:
            items = items.filter(**{lookup_field: value})
    return items.distinct()


def _filter_querystring(request: HttpRequest) -> str:
    """Current filter params (minus paging/view/partial) — for infinite-scroll & toggle links."""
    params = request.GET.copy()
    for transient in ("page", "view", "partial"):
        params.pop(transient, None)
    return params.urlencode()


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
    lab = request.lab
    query = request.GET.get("q", "")
    facets = {param: request.GET.get(param, "") for param in _FACETS}
    view_mode = _resolve_view_mode(request)
    items = _filtered_items(lab, query, facets)

    page = Paginator(items, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "query": query,
        "facets": facets,
        "view_mode": view_mode,
        "filter_qs": _filter_querystring(request),
        "has_filters": bool(query.strip()) or any(facets.values()),
        "tags": Tag.objects.filter(lab=lab).order_by("name"),
        "locations": Location.objects.filter(lab=lab).order_by("name"),
        "vendors": Vendor.objects.filter(lab=lab).order_by("name"),
        "owners": User.objects.filter(owned_items__lab=lab).distinct().order_by("email"),
        "can_manage": request.user.can(lab, "manage_inventory"),
    }
    if request.GET.get("partial") == "chunk":
        # Infinite scroll: append just the next page of rows/cards.
        return render(request, "inventory/_item_chunk.html", context)
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
    entries = (
        AuditEntry.objects.filter(lab=request.lab, target_type="Item", target_id=str(item.pk))
        .select_related("actor")
        .order_by("-timestamp")[:50]
    )
    return render(
        request,
        "inventory/item_detail.html",
        {
            "item": item,
            "custom_fields": _custom_field_rows(request.lab, item),
            "can_manage": request.user.can(request.lab, "manage_inventory"),
            "entries": entries,
            "comments": Comment.for_object(item),
            "attachments": Attachment.for_object(item),
        },
    )


def _custom_field_rows(lab, item: Item) -> list[tuple[str, object]]:
    """Pair each stored custom-field value with its human label from the lab pool."""
    labels = dict(
        lab.field_definitions.values_list("key", "label")  # type: ignore[attr-defined]
    )
    return [(labels.get(key, key), value) for key, value in sorted(item.custom_fields.items())]


@require_permission("view_inventory")
def item_label(request: HttpRequest, pk: int) -> HttpResponse:
    """Print-friendly label page for an item: its frozen ID plus labelling instructions."""
    item = get_object_or_404(Item, pk=pk, lab=request.lab)
    return render(request, "inventory/item_label.html", {"item": item})


@require_permission("manage_inventory")
def item_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ItemForm(request.POST, lab=request.lab)
        if form.is_valid():
            item = form.save(commit=False)  # form assigns the chosen/next-free human_id
            item.lab = request.lab
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


@require_permission("view_inventory")
@require_GET
def ghs_lookup(request: HttpRequest) -> JsonResponse:
    """Suggest GHS data (signal word, H/P statements, pictograms) for a CAS number.

    Backs the "Look up by CAS" button on the item and request forms. Best-effort:
    an unknown CAS or an unreachable PubChem yields ``{"found": false}``, never an
    error the form would have to handle.
    """
    cas = ghs_lookup_client.normalize_cas(request.GET.get("cas", ""))
    if not ghs_lookup_client.CAS_RE.match(cas):
        return JsonResponse({"error": "invalid_cas"}, status=400)
    suggestion = ghs_lookup_client.lookup_cas(cas)
    if suggestion is None:
        return JsonResponse({"found": False})

    statements = HazardStatement.objects.in_bulk(suggestion.hazard_codes)
    has_notifier_data = bool(suggestion.percentages)
    ordered = [
        code
        for code in sorted(suggestion.hazard_codes, key=lambda c: (c.startswith("P"), c))
        if code in statements
    ]

    harmonized = {code for code in suggestion.harmonized_codes if code in statements}

    def h_suggested(code: str) -> bool:
        # The EU harmonised classification (CLP Annex VI) is legally binding — when
        # present it decides exactly which codes are auto-selected.
        if harmonized:
            return code in harmonized
        percent = suggestion.percentages.get(code)
        if percent is not None:
            return percent >= ghs_lookup_client.SUGGEST_CUTOFF_PERCENT
        # An unannotated H-code next to annotated ones comes from a minor side
        # source — treat it as rare. With no notifier data at all, keep everything.
        return not has_notifier_data

    # P-statements carry no notifier shares; rank them by whether the GHS recommends
    # them for the H-codes we just accepted. No mapping data -> keep them all.
    accepted_h = [
        code
        for code in ordered
        if statements[code].kind != HazardStatement.Kind.P and h_suggested(code)
    ]
    recommended = ghs.recommended_p_parts(accepted_h)

    hazards = []
    for code in ordered:
        if statements[code].kind == HazardStatement.Kind.P:
            suggested = recommended is None or ghs.is_recommended_p(code, recommended)
        else:
            suggested = h_suggested(code)
        hazards.append(
            {
                "code": code,
                "text": statements[code].text_en,
                "kind": statements[code].kind,
                "percent": suggestion.percentages.get(code),
                "suggested": suggested,
            }
        )
    return JsonResponse(
        {
            "found": True,
            "signal_word": suggestion.signal_word,
            "hazards": hazards,
            "pictograms": [
                {
                    "name": name,
                    "code": ghs_lookup_client.PICTOGRAM_CODES.get(name),
                    "icon": static(f"img/ghs/{ghs_lookup_client.PICTOGRAM_CODES[name]}.svg")
                    if name in ghs_lookup_client.PICTOGRAM_CODES
                    else None,
                }
                for name in suggestion.pictograms
            ],
        }
    )


@login_required
@require_POST
def switch_lab(request: HttpRequest, slug: str) -> HttpResponse:
    """Set the session's active lab (must be one the user belongs to), then go to it."""
    lab = get_object_or_404(user_labs(request.user), slug=slug)
    set_current_lab(request, lab)
    target = request.POST.get("next", "")
    if not target or not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = reverse("inventory:item_list")  # ignore off-site targets (open-redirect guard)
    return redirect(target)
