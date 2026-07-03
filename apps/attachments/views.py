"""Uploading, downloading, and deleting attachments.

Only a whitelisted set of models is attachable. Viewing/downloading is gated on the
target type's view permission; adding and deleting on its write permission (fail
closed). Files are never served from MEDIA_URL — downloads always pass through here.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEntry
from apps.inventory.models import Item
from apps.procurement.models import Request
from apps.tenancy.scoping import get_current_lab

from .forms import AttachmentForm
from .models import Attachment

# slug -> (model, view permission, write permission, detail url name)
ATTACHABLE = {
    "item": (Item, "view_inventory", "manage_inventory", "inventory:item_detail"),
    "request": (Request, "view_requests", "create_request", "procurement:request_detail"),
}


def _spec_for_instance(attachment: Attachment) -> tuple:
    for spec in ATTACHABLE.values():
        if isinstance(attachment.target, spec[0]):
            return spec
    raise Http404("Not an attachable target")


@login_required
@require_POST
def add_attachment(request: HttpRequest, model: str, pk: int) -> HttpResponse:
    spec = ATTACHABLE.get(model)
    if spec is None:
        raise Http404("Not attachable")
    model_cls, _view_perm, write_perm, detail_url = spec

    lab = get_current_lab(request)
    if lab is None or not request.user.can(lab, write_perm):
        raise PermissionDenied

    target = get_object_or_404(model_cls, pk=pk, lab=lab)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        upload = form.cleaned_data["file"]
        attachment = Attachment.objects.create(
            lab=lab,
            uploaded_by=request.user,
            target=target,
            file=upload,
            original_name=upload.name,
            size=upload.size,
        )
        AuditEntry.record(
            lab=lab,
            actor=request.user,
            action="attachments.added",
            target=target,
            changes={"file": attachment.original_name},
        )
    else:
        for error in form.errors["file"]:
            messages.error(request, error)
    return redirect(reverse(detail_url, args=[pk]) + "#attachments")


@login_required
def download_attachment(request: HttpRequest, pk: int) -> FileResponse:
    lab = get_current_lab(request)
    if lab is None:
        raise PermissionDenied
    attachment = get_object_or_404(Attachment, pk=pk, lab=lab)
    _model, view_perm, _write_perm, _detail_url = _spec_for_instance(attachment)
    if not request.user.can(lab, view_perm):
        raise PermissionDenied
    return FileResponse(
        attachment.file.open("rb"), as_attachment=True, filename=attachment.original_name
    )


@login_required
@require_POST
def delete_attachment(request: HttpRequest, pk: int) -> HttpResponse:
    lab = get_current_lab(request)
    if lab is None:
        raise PermissionDenied
    attachment = get_object_or_404(Attachment, pk=pk, lab=lab)
    _model, _view_perm, write_perm, detail_url = _spec_for_instance(attachment)
    if not request.user.can(lab, write_perm):
        raise PermissionDenied

    target, name = attachment.target, attachment.original_name
    attachment.delete()
    AuditEntry.record(
        lab=lab,
        actor=request.user,
        action="attachments.removed",
        target=target,
        changes={"file": name},
    )
    messages.success(request, f"Attachment “{name}” removed.")
    return redirect(reverse(detail_url, args=[target.pk]) + "#attachments")
