"""Posting comments. Only a whitelisted set of models is commentable, each gated on the
view permission for its type and scoped to the active lab."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.inventory.models import Item
from apps.procurement.models import Request
from apps.tenancy.scoping import get_current_lab

from .forms import CommentForm
from .models import Comment

# slug -> (model, required view permission, detail url name)
COMMENTABLE = {
    "item": (Item, "view_inventory", "inventory:item_detail"),
    "request": (Request, "view_requests", "procurement:request_detail"),
}


@login_required
@require_POST
def add_comment(request: HttpRequest, model: str, pk: int) -> HttpResponse:
    spec = COMMENTABLE.get(model)
    if spec is None:
        raise Http404("Not commentable")
    model_cls, permission, detail_url = spec

    lab = get_current_lab(request)
    if lab is None or not request.user.can(lab, permission):
        raise PermissionDenied

    target = get_object_or_404(model_cls, pk=pk, lab=lab)
    form = CommentForm(request.POST)
    if form.is_valid():
        Comment.objects.create(
            lab=lab, author=request.user, target=target, body=form.cleaned_data["body"]
        )
    else:
        messages.error(request, "A comment can't be empty.")
    return redirect(reverse(detail_url, args=[pk]) + "#comments")
