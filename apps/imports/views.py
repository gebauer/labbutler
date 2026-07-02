"""Generic spreadsheet import wizard: upload → map columns → preview → commit.

State between steps lives in the session (the uploaded file is stashed in default storage
under a random name); nothing is written to inventory until the final commit. Every step
is gated on the ``import_inventory`` permission and scoped to ``request.lab``.
"""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.core.files.storage import default_storage
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.tenancy.scoping import require_permission

from . import generic
from .service import commit

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = (".xlsx", ".xlsm")
PREVIEW_LIMIT = 15

# Session keys holding wizard state.
FILE_KEY = "import_file"
NAME_KEY = "import_filename"
SHEET_KEY = "import_sheet"
MAPPING_KEY = "import_mapping"


def _cleanup(request: HttpRequest) -> None:
    """Delete the stashed upload and clear all wizard state from the session."""
    name = request.session.get(FILE_KEY)
    if name and default_storage.exists(name):
        default_storage.delete(name)
    for key in (FILE_KEY, NAME_KEY, SHEET_KEY, MAPPING_KEY):
        request.session.pop(key, None)


@require_permission("import_inventory")
def start(request: HttpRequest) -> HttpResponse:
    """Step 1: upload a spreadsheet."""
    if request.method == "POST":
        upload = request.FILES.get("spreadsheet")
        error = _validate_upload(upload)
        if error:
            messages.error(request, error)
            return redirect("imports:start")

        _cleanup(request)  # drop any half-finished previous run
        stored_name = default_storage.save(f"imports/{uuid.uuid4().hex}.xlsx", upload)
        try:
            names = generic.sheet_names(default_storage.path(stored_name))
        except Exception:
            default_storage.delete(stored_name)
            messages.error(request, "That file could not be read as a spreadsheet.")
            return redirect("imports:start")

        request.session[FILE_KEY] = stored_name
        request.session[NAME_KEY] = upload.name
        request.session[SHEET_KEY] = names[0]
        request.session.pop(MAPPING_KEY, None)
        return redirect("imports:mapping")

    return render(request, "imports/start.html")


def _validate_upload(upload) -> str | None:
    if upload is None:
        return "Choose a spreadsheet to upload."
    if not upload.name.lower().endswith(ALLOWED_SUFFIXES):
        return "Only .xlsx / .xlsm spreadsheets are supported."
    if upload.size > MAX_UPLOAD_BYTES:
        return "That file is too large (limit 10 MB)."
    return None


@require_permission("import_inventory")
def mapping(request: HttpRequest) -> HttpResponse:
    """Step 2: choose the sheet and map each column to an item field."""
    stored_name = request.session.get(FILE_KEY)
    if not stored_name:
        return redirect("imports:start")
    path = default_storage.path(stored_name)

    if request.method == "POST":
        sheet = request.POST.get("sheet") or request.session[SHEET_KEY]
        columns = generic.read_columns(path, sheet)
        chosen = {
            header: request.POST.get(f"col-{i}", generic.IGNORE)
            for i, header in enumerate(columns.headers)
            if header
        }
        errors = generic.validate_mapping(chosen)
        if errors:
            for error in errors:
                messages.error(request, error)
            return _render_mapping(request, columns, chosen)
        request.session[SHEET_KEY] = sheet
        request.session[MAPPING_KEY] = chosen
        return redirect("imports:preview")

    sheet = request.GET.get("sheet") or request.session.get(SHEET_KEY)
    columns = generic.read_columns(path, sheet)
    request.session[SHEET_KEY] = columns.sheet
    saved = request.session.get(MAPPING_KEY) or {}
    selected = {
        header: saved.get(header) or generic.guess_target(header)
        for header in columns.headers
        if header
    }
    return _render_mapping(request, columns, selected)


def _render_mapping(request, columns, selected) -> HttpResponse:
    column_rows = [
        {
            "index": i,
            "header": header,
            "selected": selected.get(header, generic.IGNORE),
            "samples": [row[i] if i < len(row) else "" for row in columns.preview_rows],
        }
        for i, header in enumerate(columns.headers)
        if header
    ]
    return render(
        request,
        "imports/mapping.html",
        {
            "filename": request.session.get(NAME_KEY, ""),
            "sheet_names": columns.sheet_names,
            "sheet": columns.sheet,
            "columns": column_rows,
            "choices": generic.TARGET_CHOICES,
        },
    )


@require_permission("import_inventory")
def preview(request: HttpRequest) -> HttpResponse:
    """Step 3: dry-run preview, then commit."""
    stored_name = request.session.get(FILE_KEY)
    mapping_spec = request.session.get(MAPPING_KEY)
    if not stored_name or not mapping_spec:
        return redirect("imports:start")
    path = default_storage.path(stored_name)
    sheet = request.session[SHEET_KEY]

    try:
        plan = generic.plan_from_file(path, sheet, mapping_spec)
    except generic.ImportTooLarge as exc:
        _cleanup(request)
        messages.error(request, f"Import cancelled: {exc}.")
        return redirect("imports:start")

    if request.method == "POST":
        filename = request.session.get(NAME_KEY, "the file")
        result = commit(plan, lab=request.lab, actor=request.user)
        _cleanup(request)
        messages.success(
            request,
            f"Imported {result.created} item(s) ({result.skipped} skipped) from {filename}.",
        )
        return redirect("inventory:item_list")

    sample = [r for r in plan.rows if not r.skip][:PREVIEW_LIMIT]
    return render(
        request,
        "imports/preview.html",
        {
            "filename": request.session.get(NAME_KEY, ""),
            "counts": plan.counts(),
            "summary": plan.summary(),
            "sample": sample,
            "truncated": len(plan.rows) > PREVIEW_LIMIT,
        },
    )


@require_permission("import_inventory")
def cancel(request: HttpRequest) -> HttpResponse:
    _cleanup(request)
    messages.info(request, "Import cancelled.")
    return redirect("inventory:item_list")
