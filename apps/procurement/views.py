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
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEntry
from apps.tenancy.scoping import require_permission

from . import services
from .forms import RequestForm
from .models import Request

PAGE_SIZE = 25


@require_permission("view_requests")
def request_list(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status", "")
    requests = (
        Request.objects.filter(lab=request.lab)
        .select_related("vendor", "budget", "requested_by")
        .order_by("-created_at")
    )
    if status in Request.Status.values:
        requests = requests.filter(status=status)

    page = Paginator(requests, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "procurement/request_list.html",
        {
            "page": page,
            "status": status,
            "statuses": Request.Status.choices,
            "can_create": request.user.can(request.lab, "create_request"),
        },
    )


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
    return render(
        request,
        "procurement/request_detail.html",
        {
            "req": req,
            "transitions": services.available_transitions(request.user, req),
            "editable": editable,
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
    if action == "check_in" and req.created_item_id:
        return redirect("inventory:item_detail", pk=req.created_item_id)
    return redirect("procurement:request_detail", pk=req.pk)
