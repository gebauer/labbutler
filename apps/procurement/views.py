"""Procurement screens: a filterable request list, detail with workflow actions, and
create/edit forms.

Reads are gated on ``view_requests`` and raising a request on ``create_request``; each
workflow action re-checks the specific permission through
:func:`apps.procurement.services.may_perform` and fails closed.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.attachments.forms import MAX_SIZE_MB
from apps.attachments.models import Attachment
from apps.audit.models import AuditEntry
from apps.comments.models import Comment
from apps.inventory import ids
from apps.inventory.models import Item, Location
from apps.tenancy.models import User
from apps.tenancy.scoping import require_permission

from . import services, suggestions
from .forms import RequestForm
from .models import PurchaseOrder, Request, Vendor

PAGE_SIZE = 25

# Free-text query columns, and facet param -> the related pk it filters on. The requester
# is searchable by both email (the identity) and friendly name (the display label).
_REQ_SEARCH_FIELDS = (
    "item_name",
    "catalog_number",
    "cas_number",
    "po_number",
    "requested_by__email",
    "requested_by__friendly_name",
)
_REQ_FACETS = {
    "vendor": "vendor__pk",
    "requester": "requested_by__pk",
    "assignee": "assigned_to__pk",
}


def _filtered_requests(
    lab, query: str, statuses: list[str], facets: dict[str, str], *, user=None, mine=False
):
    """Narrow a lab's requests by search text, any selected statuses, and facet filters.

    ``mine`` scopes to requests the given ``user`` is involved in — raised by them or
    forwarded to them to order — which the AND-only facets cannot express on their own.
    """
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
    valid_statuses: list[str] = []
    for code in statuses:
        if code in _STAGE_STATUSES:
            valid_statuses.extend(_STAGE_STATUSES[code])
        elif code in Request.Status.values:
            # Plain status codes (e.g. bookmarked pre-stage URLs) still filter.
            valid_statuses.append(code)
    if valid_statuses:
        requests = requests.filter(status__in=valid_statuses)
    for param, lookup_field in _REQ_FACETS.items():
        value = facets.get(param)
        if value:
            requests = requests.filter(**{lookup_field: value})
    if mine and user is not None:
        requests = requests.filter(Q(requested_by=user) | Q(assigned_to=user))
    return requests


# Filter chips group statuses into stages: "delivered" covers every arrived state
# (Delivered = awaiting check-in, Checked in, Received untracked) because the
# distinction matters on the request detail, not when scanning the list. "approved"
# also covers the central-purchasing detour (PO created/signed/sent): the order is
# approved but not yet placed.
_STAGE_STATUSES: dict[str, tuple[str, ...]] = {
    "requested": ("requested",),
    "approved": ("approved", "po_created", "po_signed", "po_sent"),
    "ordered": ("ordered",),
    "delivered": ("delivered", "checked_in", "received"),
    "rejected": ("rejected",),
    "cancelled": ("cancelled",),
}
# The happy-path pipeline shown as a stepper (off-path states handled separately).
_PIPELINE = ["requested", "approved", "ordered", "delivered"]
_OFF_PATH = ["rejected", "cancelled"]


def _status_overview(lab, selected: list[str]) -> tuple[list[dict], list[dict]]:
    """Per-stage counts (lab-wide) for the pipeline stepper and the off-path chips."""
    counts = dict(Request.objects.filter(lab=lab).values_list("status").annotate(n=Count("id")))
    labels = dict(Request.Status.choices)

    def stage(code: str) -> dict:
        return {
            "code": code,
            "label": labels[code],
            "count": sum(counts.get(status, 0) for status in _STAGE_STATUSES[code]),
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
    mine = request.GET.get("mine") == "1"
    requests = _filtered_requests(
        lab, query, selected_statuses, facets, user=request.user, mine=mine
    )

    page = Paginator(requests, PAGE_SIZE).get_page(request.GET.get("page"))
    pipeline, off_path = _status_overview(lab, selected_statuses)
    context = {
        "page": page,
        "query": query,
        "selected_statuses": selected_statuses,
        "facets": facets,
        "mine": mine,
        "pipeline": pipeline,
        "off_path": off_path,
        "filter_qs": _request_querystring(request),
        "has_filters": bool(query.strip())
        or bool(selected_statuses)
        or any(facets.values())
        or mine,
        "vendors": Vendor.objects.filter(lab=lab).order_by("name"),
        "requesters": User.objects.filter(requests_made__lab=lab).distinct().order_by("email"),
        "assignees": services.forward_recipients(lab),
        "can_create": request.user.can(lab, "create_request"),
    }
    if request.GET.get("partial") == "chunk":
        return render(request, "procurement/_request_rows.html", context)
    if request.htmx:
        return render(request, "procurement/_request_results.html", context)
    return render(request, "procurement/request_list.html", context)


# Statuses on which the route nudge is meaningful: the decision is still open.
_ROUTE_SUGGESTIBLE = frozenset(
    {
        Request.Status.REQUESTED,
        Request.Status.APPROVED,
        Request.Status.PO_CREATED,
        Request.Status.PO_SIGNED,
    }
)


def _form_fill_summary(req: Request) -> list[dict]:
    """Label/value rows in the order the official Beschaffungsantrag asks for them.

    The manual bridge until prefill exists: filling the form stays outside LabButler,
    but nobody retypes — each row gets a copy-to-clipboard button in the template.
    """
    requester = req.requested_by
    if req.includes_taxes:
        vat_rate = req.lab.default_vat_rate
        net_unit = (req.unit_price / (1 + vat_rate)).quantize(Decimal("0.01"))
    else:
        net_unit = req.unit_price
    rows = [
        ("Requester name", requester.display_name if requester else ""),
        ("Requester email", requester.email if requester else ""),
        ("Delivery address", req.shipping_address.address if req.shipping_address_id else ""),
        ("Kostenstelle / PSP", f"{req.budget.number} · {req.budget.name}" if req.budget_id else ""),
        ("Item", req.item_name),
        ("Catalog no.", req.catalog_number),
        ("Quantity (packs)", str(req.pack_count)),
        ("Unit price (net)", f"{net_unit} {req.currency}"),
        ("Net total", f"{req.net_total} {req.currency}"),
        ("Vendor", req.vendor.name if req.vendor_id else ""),
        ("Vendor country", (req.vendor.country or "") if req.vendor_id else ""),
    ]
    return [{"label": label, "value": value} for label, value in rows if value]


@require_permission("view_requests")
def request_detail(request: HttpRequest, pk: int) -> HttpResponse:
    req = get_object_or_404(
        Request.objects.select_related(
            "vendor",
            "budget",
            "shipping_address",
            "requested_by",
            "approver",
            "created_item",
            "source_item",
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

    # Central purchasing: nudges are computed fresh on every render (never stored) and
    # the two suggestions are independent — a route nudge and a PO-refresh nudge can
    # coexist or appear alone.
    route_suggestion = None
    if req.status in _ROUTE_SUGGESTIBLE:
        candidate = suggestions.suggest_route(req)
        if candidate.route != req.procurement_route:
            route_suggestion = candidate
    active_po = req.active_purchase_order()
    po_refresh = None
    if active_po is not None and req.status in _ROUTE_SUGGESTIBLE:
        candidate = suggestions.suggest_po_refresh(active_po, req.net_total)
        if candidate.should_refresh:
            po_refresh = candidate
    is_central = req.procurement_route == Request.Route.CENTRAL

    return render(
        request,
        "procurement/request_detail.html",
        {
            "req": req,
            "transitions": services.available_transitions(request.user, req),
            "can_receive": services.can_receive(request.user, req),
            "can_forward": services.can_forward(request.user, req),
            "can_self_approve": services.can_self_approve(request.user, req),
            "editable": editable,
            "entries": entries,
            "comments": Comment.for_object(req),
            "attachments": Attachment.for_object(req),
            "can_attach": request.user.can(request.lab, "create_request"),
            "can_create": request.user.can(request.lab, "create_request"),
            "route_suggestion": route_suggestion,
            "active_po": active_po,
            "po_refresh": po_refresh,
            "can_create_po": services.can_create_po(request.user, req),
            "can_upload_signed_po": services.can_upload_signed_po(request.user, req),
            "can_reroute": services.can_reroute(request.user, req),
            "can_resend_zk_email": services.can_resend_zk_email(request.user, req),
            "fill_summary": _form_fill_summary(req) if is_central else [],
            "routes": Request.Route.choices,
            "override_reasons": services.OVERRIDE_REASONS,
            "manager": services.request_manager(req),
        },
    )


# Fields copied verbatim when a request is duplicated for a reorder. Workflow state,
# budget, shipping address, delivery date, PO/quote and attachments start fresh.
_REORDER_FIELDS = (
    "item_name",
    "catalog_number",
    "cas_number",
    "product_url",
    "unit_price",
    "currency",
    "pack_count",
    "signal_word",
    "storage_class",
)


def _reorder_source(request: HttpRequest) -> tuple[Request | None, Item | None]:
    """Resolve the ``from_request`` / ``from_item`` reorder parameter, lab-scoped."""
    for param, model in (("from_request", Request), ("from_item", Item)):
        raw_pk = request.GET.get(param)
        if raw_pk:
            if not raw_pk.isdigit():
                raise Http404
            source = get_object_or_404(model, pk=raw_pk, lab=request.lab)
            return (source, None) if model is Request else (None, source)
    return None, None


def _initial_from_request(source: Request) -> dict:
    initial: dict = {name: getattr(source, name) for name in _REORDER_FIELDS}
    initial["vendor"] = source.vendor_id
    initial["tags"] = list(source.tags.values_list("pk", flat=True))
    initial["hazards"] = list(source.hazards.values_list("pk", flat=True))
    return {name: value for name, value in initial.items() if value not in (None, "", [])}


def _initial_from_item(item: Item) -> dict:
    # The request the item was checked in from has the richer data (URL, pack count,
    # price at order time); fall back to the item's own fields for imported stock.
    source = Request.objects.filter(created_item=item).first()
    if source is not None:
        return _initial_from_request(source)
    initial: dict = {
        "item_name": item.name,
        "catalog_number": item.catalog_number,
        "cas_number": item.cas_number,
        "product_url": item.product_url,
        "vendor": item.vendor_id,
        "unit_price": item.price_amount,
        "currency": item.price_currency,
        "signal_word": item.signal_word,
        "storage_class": item.storage_class,
        "tags": list(item.tags.values_list("pk", flat=True)),
        "hazards": list(item.hazards.values_list("pk", flat=True)),
    }
    return {name: value for name, value in initial.items() if value not in (None, "", [])}


def _route_suggestion_config(form: RequestForm) -> dict:
    """Inputs for the client-side mirror of :func:`suggestions.suggest_route`.

    Serialized into the form page (via ``json_script``) so the route nudge can react
    live while typing; the server recomputes the suggestion on save regardless.
    """
    return {
        "threshold": str(suggestions.central_purchasing_threshold(form.lab)),
        "euCountries": sorted(suggestions.eu_countries()),
        "vendorCountries": {
            str(pk): country
            for pk, country in form.fields["vendor"].queryset.values_list("pk", "country")
            if country
        },
    }


def _record_form_save_override(request: HttpRequest, req: Request) -> None:
    """Audit keeping DIRECT against a CENTRAL suggestion when the form saves.

    Same contract as at order time: the event is mandatory, the reason (collected by
    the bypass modal, absent without JS) is optional.
    """
    if req.procurement_route != Request.Route.DIRECT:
        return
    suggestion = suggestions.suggest_route(req)
    if suggestion.route != Request.Route.CENTRAL:
        return
    services.record_route_override(
        req,
        actor=request.user,
        suggestion=suggestion,
        reason_code=request.POST.get("override_reason_code", ""),
        reason_text=(request.POST.get("override_reason_text") or "").strip(),
    )


@require_permission("create_request")
def request_create(request: HttpRequest) -> HttpResponse:
    # The form posts back to the same URL, so the reorder params survive into the POST.
    source_request, source_item = _reorder_source(request)
    if request.method == "POST":
        form = RequestForm(request.POST, request.FILES, lab=request.lab)
        if form.is_valid():
            req = form.save(commit=False)
            req.lab = request.lab
            req.requested_by = request.user
            req.source_item = source_item
            req.recalculate_totals()
            req.save()
            form.save_m2m()
            form.save_attachments(user=request.user)
            changes = {"item_name": req.item_name, "total": str(req.total)}
            if source_item is not None:
                changes["reordered_from_item"] = source_item.human_id
            elif source_request is not None:
                changes["duplicated_from_request"] = source_request.pk
            AuditEntry.record(
                lab=request.lab,
                actor=request.user,
                action="procurement.request_created",
                target=req,
                changes=changes,
            )
            _record_form_save_override(request, req)
            # Notify the lab's approvers (once the row is committed) that it needs approval.
            from apps.notifications.tasks import notify_request_created

            transaction.on_commit(lambda: notify_request_created.delay(req.pk))
            messages.success(request, "Request raised.")
            return redirect("procurement:request_detail", pk=req.pk)
    else:
        initial = None
        if source_request is not None:
            initial = _initial_from_request(source_request)
        elif source_item is not None:
            initial = _initial_from_item(source_item)
        form = RequestForm(lab=request.lab, initial=initial)
    return render(
        request,
        "procurement/request_form.html",
        {
            "form": form,
            "title": "New request",
            "req": None,
            "route_config": _route_suggestion_config(form),
            "override_reasons": services.OVERRIDE_REASONS,
        },
    )


@require_permission("create_request")
def request_edit(request: HttpRequest, pk: int) -> HttpResponse:
    req = get_object_or_404(Request, pk=pk, lab=request.lab)
    # Only an open (not yet approved) request can still be edited.
    if req.status != Request.Status.REQUESTED:
        messages.error(request, "Only a request that is still 'Requested' can be edited.")
        return redirect("procurement:request_detail", pk=req.pk)

    if request.method == "POST":
        form = RequestForm(request.POST, request.FILES, instance=req, lab=request.lab)
        if form.is_valid():
            req = form.save(commit=False)
            req.recalculate_totals()
            req.save()
            form.save_m2m()
            form.save_attachments(user=request.user)
            _record_form_save_override(request, req)
            messages.success(request, "Request updated.")
            return redirect("procurement:request_detail", pk=req.pk)
    else:
        form = RequestForm(instance=req, lab=request.lab)
    return render(
        request,
        "procurement/request_form.html",
        {
            "form": form,
            "title": f"Edit request #{req.pk}",
            "req": req,
            "route_config": _route_suggestion_config(form),
            "override_reasons": services.OVERRIDE_REASONS,
        },
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
            req,
            action,
            actor=request.user,
            po_number=request.POST.get("po_number", ""),
            zk_order_number=(request.POST.get("zk_order_number") or "").strip(),
            override_reason_code=request.POST.get("override_reason_code", ""),
            override_reason_text=(request.POST.get("override_reason_text") or "").strip(),
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

    # Depth-first with cached paths, so the dropdown shows unambiguous full paths.
    locations = Location.tree_for_lab(request.lab)

    def dialog(**extra):
        context = {
            "req": req,
            "locations": locations,
            "id_suggestions": ids.suggest_ids(request.lab),
            "attachment_count": Attachment.for_object(req).count(),
        }
        context.update(extra)
        return render(request, "procurement/receive.html", context)

    if request.method == "POST":
        if request.POST.get("outcome") == "no_item":
            services.receive(req, actor=request.user, create_item=False)
            messages.success(request, "Recorded as received — no inventory item created.")
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

        location = Location.objects.filter(
            lab=request.lab, pk=request.POST.get("location") or 0
        ).first()
        if location is None and not request.POST.get("confirm_no_location"):
            # Checking in with no location is allowed, but only after an explicit confirm.
            return dialog(warn_no_location=True, entered_id=human_id)

        services.receive(
            req,
            actor=request.user,
            create_item=True,
            location=location,
            human_id=human_id,
            carry_attachments=bool(request.POST.get("carry_attachments")),
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
    coordinators = services.forward_recipients(request.lab)

    if request.method == "POST":
        assignee = coordinators.filter(pk=request.POST.get("assignee") or 0).first()
        if assignee is None:
            messages.error(request, "Choose a purchase coordinator.")
        else:
            services.forward(req, actor=request.user, assignee=assignee)
            messages.success(request, f"Forwarded to {assignee.email} for ordering.")
            return redirect("procurement:request_detail", pk=req.pk)

    return render(request, "procurement/forward.html", {"req": req, "coordinators": coordinators})


# --- Central purchasing (Zentraleinkauf) ---------------------------------------------


def _po_upload_error(upload) -> str:
    """Validation for PO uploads: PDF only, size-capped. v1 never opens the file."""
    if upload is None:
        return "Choose a PDF file to upload."
    if not upload.name.lower().endswith(".pdf"):
        return "The order form must be a PDF."
    if upload.size > MAX_SIZE_MB * 1024 * 1024:
        return f"File is too large (max {MAX_SIZE_MB} MB)."
    return ""


@require_permission("view_requests")
@require_POST
def request_po_upload(request: HttpRequest, pk: int) -> HttpResponse:
    """Attach the filled official order form (Approved → PO created, or replace)."""
    req = get_object_or_404(Request, pk=pk, lab=request.lab)
    if not services.can_create_po(request.user, req):
        raise PermissionDenied
    upload = request.FILES.get("po_pdf")
    error = _po_upload_error(upload)
    if error:
        messages.error(request, error)
        return redirect("procurement:request_detail", pk=req.pk)
    try:
        services.create_po(req, actor=request.user, upload=upload)
    except services.TransitionError as exc:
        messages.error(request, str(exc))
        return redirect("procurement:request_detail", pk=req.pk)
    messages.success(request, "Order form uploaded — the signers have been notified.")
    return redirect("procurement:request_detail", pk=req.pk)


@require_permission("view_requests")
@require_POST
def request_po_upload_signed(request: HttpRequest, pk: int) -> HttpResponse:
    """Upload the signed order form (PO created → PO signed)."""
    req = get_object_or_404(Request, pk=pk, lab=request.lab)
    if not services.can_upload_signed_po(request.user, req):
        raise PermissionDenied
    upload = request.FILES.get("po_pdf")
    error = _po_upload_error(upload)
    if error:
        messages.error(request, error)
        return redirect("procurement:request_detail", pk=req.pk)
    try:
        services.upload_signed_po(req, actor=request.user, upload=upload)
    except services.TransitionError as exc:
        messages.error(request, str(exc))
        return redirect("procurement:request_detail", pk=req.pk)
    messages.success(
        request,
        "Signed order form uploaded — the forward-ready email is on its way to the "
        "request's manager.",
    )
    return redirect("procurement:request_detail", pk=req.pk)


@require_permission("view_requests")
def request_po_download(request: HttpRequest, pk: int, po_pk: int, kind: str) -> HttpResponse:
    """Permission-gated download of a PO file; never web-served from MEDIA directly."""
    req = get_object_or_404(Request, pk=pk, lab=request.lab)
    po = get_object_or_404(PurchaseOrder, pk=po_pk, request=req)
    if kind == "unsigned":
        file, suffix = po.unsigned_pdf, ""
    elif kind == "signed":
        file, suffix = po.signed_pdf, "_signiert"
    else:
        raise Http404
    if not file:
        raise Http404
    filename = f"Beschaffungsantrag_Request_{req.pk}{suffix}.pdf"
    return FileResponse(file.open("rb"), as_attachment=True, filename=filename)


@require_permission("view_requests")
@require_POST
def request_reroute(request: HttpRequest, pk: int) -> HttpResponse:
    """Manually switch the procurement route (mutable zone only)."""
    req = get_object_or_404(Request, pk=pk, lab=request.lab)
    if not services.can_reroute(request.user, req):
        raise PermissionDenied
    try:
        services.reroute(
            req,
            actor=request.user,
            to_route=request.POST.get("to_route", ""),
            reason_code=request.POST.get("reason_code", ""),
            reason_text=(request.POST.get("reason_text") or "").strip(),
        )
    except services.TransitionError as exc:
        messages.error(request, str(exc))
        return redirect("procurement:request_detail", pk=req.pk)
    messages.success(request, f"Route changed to “{req.get_procurement_route_display()}”.")
    return redirect("procurement:request_detail", pk=req.pk)


@require_permission("view_requests")
@require_POST
def request_resend_zk_email(request: HttpRequest, pk: int) -> HttpResponse:
    """Re-send the forward-ready ZK email to the request's current manager."""
    req = get_object_or_404(Request, pk=pk, lab=request.lab)
    if not services.can_resend_zk_email(request.user, req):
        raise PermissionDenied
    from apps.notifications.tasks import send_zk_forward_email

    manager = services.request_manager(req)
    transaction.on_commit(lambda: send_zk_forward_email.delay(req.pk))
    messages.success(
        request,
        f"Forward-ready email sent to {manager.email if manager else 'the request manager'}.",
    )
    return redirect("procurement:request_detail", pk=req.pk)


@require_permission("view_requests")
def request_self_approve(request: HttpRequest, pk: int) -> HttpResponse:
    """Confirmation dialog for approving one's own request (needs the self_approve right)."""
    req = get_object_or_404(Request, pk=pk, lab=request.lab)
    if not services.can_self_approve(request.user, req):
        raise PermissionDenied

    if request.method == "POST":
        if not request.POST.get("confirm"):
            messages.error(request, "Please tick the box to confirm the self-approval.")
            return render(request, "procurement/self_approve.html", {"req": req})
        services.self_approve(
            req, actor=request.user, note=(request.POST.get("note") or "").strip()
        )
        messages.success(request, "Request self-approved.")
        return redirect("procurement:request_detail", pk=req.pk)

    return render(request, "procurement/self_approve.html", {"req": req})
