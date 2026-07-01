"""Procurement screens: a filterable request list, detail with workflow actions, and
create/edit forms.

Reads are gated on ``view_requests`` and raising a request on ``create_request``; each
workflow action re-checks the specific permission through
:func:`apps.procurement.services.may_perform` and fails closed.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEntry
from apps.inventory import ids
from apps.inventory.models import Location
from apps.tenancy.models import User
from apps.tenancy.scoping import require_permission

from . import services
from .forms import RequestForm
from .models import Request, Vendor

PAGE_SIZE = 25

# Free-text query columns, and facet param -> the related pk it filters on.
_REQ_SEARCH_FIELDS = ("item_name", "catalog_number", "cas_number", "po_number")
_REQ_FACETS = {
    "vendor": "vendor__pk",
    "requester": "requested_by__pk",
    "assignee": "assigned_to__pk",
}


def _filtered_requests(lab, query: str, statuses: list[str], facets: dict[str, str]):
    """Narrow a lab's requests by search text, any selected statuses, and facet filters."""
    requests = (
        Request.objects.filter(lab=lab)
        .select_related("vendor", "budget", "requested_by")
        .order_by("-created_at")
    )
    query = query.strip()
    if query:
        lookup = Q()
        for field_name in _REQ_SEARCH_FIELDS:
            lookup |= Q(**{f"{field_name}__icontains": query})
        requests = requests.filter(lookup)
    valid_statuses = [s for s in statuses if s in Request.Status.values]
    if valid_statuses:
        requests = requests.filter(status__in=valid_statuses)
    for param, lookup_field in _REQ_FACETS.items():
        value = facets.get(param)
        if value:
            requests = requests.filter(**{lookup_field: value})
    return requests


# The happy-path pipeline shown as a stepper (off-path states handled separately).
_PIPELINE = ["requested", "approved", "ordered", "delivered", "checked_in"]
_OFF_PATH = ["rejected", "cancelled"]


def _status_overview(lab, selected: list[str]) -> tuple[list[dict], list[dict]]:
    """Per-status counts (lab-wide) for the pipeline stepper and the off-path chips."""
    counts = dict(Request.objects.filter(lab=lab).values_list("status").annotate(n=Count("id")))
    labels = dict(Request.Status.choices)

    def stage(code: str) -> dict:
        return {
            "code": code,
            "label": labels[code],
            "count": counts.get(code, 0),
            "checked": code in selected,
        }

    return [stage(c) for c in _PIPELINE], [stage(c) for c in _OFF_PATH]


def _request_querystring(request: HttpRequest) -> str:
    """Current filter params (minus paging/partial), preserving multiple status values."""
    params = request.GET.copy()
    for transient in ("page", "partial"):
        params.pop(transient, None)
    return params.urlencode()


@require_permission("view_requests")
def request_list(request: HttpRequest) -> HttpResponse:
    lab = request.lab
    query = request.GET.get("q", "")
    selected_statuses = request.GET.getlist("status")
    facets = {param: request.GET.get(param, "") for param in _REQ_FACETS}
    requests = _filtered_requests(lab, query, selected_statuses, facets)

    page = Paginator(requests, PAGE_SIZE).get_page(request.GET.get("page"))
    pipeline, off_path = _status_overview(lab, selected_statuses)
    context = {
        "page": page,
        "query": query,
        "selected_statuses": selected_statuses,
        "facets": facets,
        "pipeline": pipeline,
        "off_path": off_path,
        "filter_qs": _request_querystring(request),
        "has_filters": bool(query.strip()) or bool(selected_statuses) or any(facets.values()),
        "vendors": Vendor.objects.filter(lab=lab).order_by("name"),
        "requesters": User.objects.filter(requests_made__lab=lab).distinct().order_by("email"),
        "assignees": services.purchase_coordinators(lab),
        "can_create": request.user.can(lab, "create_request"),
    }
    if request.GET.get("partial") == "chunk":
        return render(request, "procurement/_request_rows.html", context)
    if request.htmx:
        return render(request, "procurement/_request_results.html", context)
    return render(request, "procurement/request_list.html", context)


@require_permission("view_requests")
def request_detail(request: HttpRequest, pk: int) -> HttpResponse:
    req = get_object_or_404(
        Request.objects.select_related(
            "vendor", "budget", "shipping_address", "requested_by", "approver", "created_item"
        ).prefetch_related("tags"),
        pk=pk,
        lab=request.lab,
    )
    editable = req.status == Request.Status.REQUESTED and request.user.can(
        request.lab, "create_request"
    )
    entries = (
        AuditEntry.objects.filter(lab=request.lab, target_type="Request", target_id=str(req.pk))
        .select_related("actor")
        .order_by("-timestamp")[:50]
    )
    return render(
        request,
        "procurement/request_detail.html",
        {
            "req": req,
            "transitions": services.available_transitions(request.user, req),
            "can_receive": services.can_receive(request.user, req),
            "can_forward": services.can_forward(request.user, req),
            "editable": editable,
            "entries": entries,
        },
    )


@require_permission("create_request")
def request_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = RequestForm(request.POST, lab=request.lab)
        if form.is_valid():
            req = form.save(commit=False)
            req.lab = request.lab
            req.requested_by = request.user
            req.recalculate_totals()
            req.save()
            form.save_m2m()
            AuditEntry.record(
                lab=request.lab,
                actor=request.user,
                action="procurement.request_created",
                target=req,
                changes={"item_name": req.item_name, "total": str(req.total)},
            )
            messages.success(request, "Request raised.")
            return redirect("procurement:request_detail", pk=req.pk)
    else:
        form = RequestForm(lab=request.lab)
    return render(
        request,
        "procurement/request_form.html",
        {"form": form, "title": "New request", "req": None},
    )


@require_permission("create_request")
def request_edit(request: HttpRequest, pk: int) -> HttpResponse:
    req = get_object_or_404(Request, pk=pk, lab=request.lab)
    # Only an open (not yet approved) request can still be edited.
    if req.status != Request.Status.REQUESTED:
        messages.error(request, "Only a request that is still 'Requested' can be edited.")
        return redirect("procurement:request_detail", pk=req.pk)

    if request.method == "POST":
        form = RequestForm(request.POST, instance=req, lab=request.lab)
        if form.is_valid():
            req = form.save(commit=False)
            req.recalculate_totals()
            req.save()
            form.save_m2m()
            messages.success(request, "Request updated.")
            return redirect("procurement:request_detail", pk=req.pk)
    else:
        form = RequestForm(instance=req, lab=request.lab)
    return render(
        request,
        "procurement/request_form.html",
        {"form": form, "title": f"Edit request #{req.pk}", "req": req},
    )


@require_permission("view_requests")
@require_POST
def request_action(request: HttpRequest, pk: int, action: str) -> HttpResponse:
    req = get_object_or_404(Request, pk=pk, lab=request.lab)
    transition = services.TRANSITIONS.get(action)
    if transition is None or not services.may_perform(request.user, req, transition):
        raise PermissionDenied
    try:
        services.perform_transition(
            req, action, actor=request.user, po_number=request.POST.get("po_number", "")
        )
    except services.TransitionError as exc:
        messages.error(request, str(exc))
        return redirect("procurement:request_detail", pk=req.pk)

    messages.success(request, f"Request moved to “{Request.Status(transition.to_status).label}”.")
    return redirect(_safe_next(request, reverse("procurement:request_detail", args=[req.pk])))


def _safe_next(request: HttpRequest, default: str) -> str:
    """Return a same-origin ``next`` target (e.g. the dashboard) or the default."""
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return default


@require_permission("check_in")
def request_receive(request: HttpRequest, pk: int) -> HttpResponse:
    """Delivery dialog: check the order into inventory, or record it delivered-untracked."""
    req = get_object_or_404(Request, pk=pk, lab=request.lab)
    if req.status not in (Request.Status.ORDERED, Request.Status.DELIVERED):
        messages.error(request, "Only an ordered request can be received.")
        return redirect("procurement:request_detail", pk=req.pk)

    locations = Location.objects.filter(lab=request.lab).order_by("name")

    def dialog(**extra):
        context = {
            "req": req,
            "locations": locations,
            "id_suggestions": ids.suggest_ids(request.lab),
        }
        context.update(extra)
        return render(request, "procurement/receive.html", context)

    if request.method == "POST":
        if request.POST.get("outcome") == "no_item":
            services.receive(req, actor=request.user, create_item=False)
            messages.success(request, "Recorded as delivered — no inventory item created.")
            return redirect("procurement:request_detail", pk=req.pk)

        raw_id = (request.POST.get("human_id") or "").strip()
        human_id = ""
        if raw_id:
            try:
                human_id = ids.normalize_item_id(request.lab, raw_id)
            except ValueError as exc:
                return dialog(id_error=str(exc), entered_id=raw_id)
            if ids.item_id_taken(request.lab, human_id):
                return dialog(id_error=f"{human_id} is already in use.", entered_id=raw_id)

        location = locations.filter(pk=request.POST.get("location") or 0).first()
        if location is None and not request.POST.get("confirm_no_location"):
            # Checking in with no location is allowed, but only after an explicit confirm.
            return dialog(warn_no_location=True, entered_id=human_id)

        services.receive(
            req, actor=request.user, create_item=True, location=location, human_id=human_id
        )
        messages.success(request, f"Checked in as {req.created_item.human_id}.")
        return redirect("inventory:item_label", pk=req.created_item_id)

    return dialog()


@require_permission("view_requests")
def request_forward(request: HttpRequest, pk: int) -> HttpResponse:
    """Forward an approved request to a purchase coordinator to place the order."""
    req = get_object_or_404(Request, pk=pk, lab=request.lab)
    if not services.can_forward(request.user, req):
        raise PermissionDenied
    coordinators = services.purchase_coordinators(request.lab)

    if request.method == "POST":
        assignee = coordinators.filter(pk=request.POST.get("assignee") or 0).first()
        if assignee is None:
            messages.error(request, "Choose a purchase coordinator.")
        else:
            services.forward(req, actor=request.user, assignee=assignee)
            messages.success(request, f"Forwarded to {assignee.email} for ordering.")
            return redirect("procurement:request_detail", pk=req.pk)

    return render(
        request, "procurement/forward.html", {"req": req, "coordinators": coordinators}
    )
