"""Pure builders for notification email content.

These take already-loaded objects and return a subject + plain-text body; they touch no
database and send nothing, so they are trivially testable. Recipient resolution and the
actual send live in :mod:`apps.notifications.tasks`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from apps.procurement.models import Request


@dataclass(frozen=True)
class EmailContent:
    subject: str
    body: str


def _link(base_url: str, path: str) -> str:
    if not base_url:
        return ""
    return f"\n\n{base_url.rstrip('/')}{path}"


def build_status_change(
    req: Request, previous: str, new: str, *, base_url: str = ""
) -> EmailContent:
    """Email announcing that a request moved from ``previous`` to ``new`` status."""
    previous_label = Request.Status(previous).label
    new_label = Request.Status(new).label
    subject = f"[LabButler] Request “{req.item_name}” is now {new_label}"

    lines = [
        f"Request: {req.item_name}",
        f"Status:  {previous_label} → {new_label}",
        f"Total:   {req.total} {req.currency}",
    ]
    if req.vendor_id:
        lines.append(f"Vendor:  {req.vendor.name}")
    if req.po_number:
        lines.append(f"PO #:    {req.po_number}")
    if new == Request.Status.CHECKED_IN and req.created_item_id:
        lines.append(f"Checked in as: {req.created_item.human_id} · {req.created_item.name}")

    body = "\n".join(lines) + _link(base_url, f"/requests/{req.pk}/")
    return EmailContent(subject, body)


def build_approval_needed(req: Request, *, base_url: str = "") -> EmailContent:
    """Email telling an approver a newly-raised request is waiting for their decision."""
    subject = f"[LabButler] Approval needed: “{req.item_name}”"
    lines = [
        "A new request is waiting for approval:",
        "",
        f"Request:   {req.item_name}",
        f"Total:     {req.total} {req.currency}",
    ]
    if req.requested_by_id and req.requested_by.email:
        lines.append(f"Requested: {req.requested_by.email}")
    if req.vendor_id:
        lines.append(f"Vendor:    {req.vendor.name}")
    body = "\n".join(lines) + _link(base_url, f"/requests/{req.pk}/")
    return EmailContent(subject, body)


def build_daily_digest(
    lab, pending_approvals: list, recent_updates: list, today: date, *, base_url: str = ""
) -> EmailContent:
    """A once-a-day per-member digest: requests awaiting their approval + their updates."""
    subject = f"[LabButler] {lab.name}: daily procurement summary"
    sections = [f"Procurement summary for {lab.name}, {today:%Y-%m-%d}."]
    if pending_approvals:
        sections.append(
            "\nAwaiting your approval:\n"
            + "\n".join(f"  {r.item_name}  ({r.total} {r.currency})" for r in pending_approvals)
        )
    if recent_updates:
        sections.append(
            "\nYour requests, recently updated:\n"
            + "\n".join(
                f"  {r.item_name}  →  {Request.Status(r.status).label}" for r in recent_updates
            )
        )
    body = "\n".join(sections) + _link(base_url, "/requests/")
    return EmailContent(subject, body)


def build_assignment(req: Request, *, base_url: str = "") -> EmailContent:
    """Email asking a purchase coordinator to place an approved, forwarded request."""
    subject = f"[LabButler] Please order “{req.item_name}”"
    lines = [
        "An approved request has been forwarded to you to order:",
        "",
        f"Request: {req.item_name}",
        f"Total:   {req.total} {req.currency}",
    ]
    if req.vendor_id:
        lines.append(f"Vendor:  {req.vendor.name}")
    if req.catalog_number:
        lines.append(f"Catalog: {req.catalog_number}")
    body = "\n".join(lines) + _link(base_url, f"/requests/{req.pk}/")
    return EmailContent(subject, body)


def build_expiry_digest(
    lab,
    expired: list,
    expiring: list,
    today: date,
    *,
    days_ahead: int,
    base_url: str = "",
) -> EmailContent:
    """Digest of items already expired and expiring within ``days_ahead`` days."""
    subject = (
        f"[LabButler] {lab.name}: {len(expired)} expired, "
        f"{len(expiring)} expiring within {days_ahead} days"
    )

    def _row(item) -> str:
        location = item.location.name if item.location_id else "—"
        return f"  {item.expiration_date:%Y-%m-%d}  {item.human_id}  {item.name}  ({location})"

    sections = [f"Expiry report for {lab.name}, generated {today:%Y-%m-%d}."]
    if expired:
        sections.append("\nAlready expired:\n" + "\n".join(_row(i) for i in expired))
    if expiring:
        sections.append(
            f"\nExpiring within {days_ahead} days:\n" + "\n".join(_row(i) for i in expiring)
        )
    body = "\n".join(sections) + _link(base_url, "/inventory/")
    return EmailContent(subject, body)
