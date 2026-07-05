"""Pure builders for notification email content.

These take already-loaded objects and return a subject + plain-text body (workflow mails
additionally carry an HTML alternative and an urgency flag); they touch no database and
send nothing, so they are trivially testable. Recipient resolution and the actual send
live in :mod:`apps.notifications.tasks`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.template.loader import render_to_string

from apps.procurement.models import Request


@dataclass(frozen=True)
class EmailContent:
    subject: str
    body: str
    # Optional HTML alternative for multipart mails; None sends plain text only.
    html: str | None = None
    # When True the sender marks the mail high-priority (X-Priority / Importance headers).
    urgent: bool = False


def _link(base_url: str, path: str) -> str:
    if not base_url:
        return ""
    return f"\n\n{base_url.rstrip('/')}{path}"


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}" if base_url else ""


def _person(user) -> str:
    """Identity line for email bodies: “Ada Lovelace (ada@x.de)”, or just the email."""
    if user is None:
        return ""
    if user.friendly_name and user.email:
        return f"{user.friendly_name} ({user.email})"
    return user.email or user.friendly_name


def _request_email(
    *,
    subject: str,
    intro: str,
    rows: list[tuple[str, str]],
    closing: str,
    action_url: str,
    action_label: str,
    urgent: bool,
    urgent_note: str,
) -> EmailContent:
    """Assemble a workflow mail (text + HTML) from one shared set of parts."""
    if urgent:
        subject = subject.replace("[LabButler] ", "[LabButler] URGENT — ", 1)

    width = max(len(label) for label, _ in rows) + 2
    lines = ([f"{urgent_note}", ""] if urgent else []) + [intro, ""]
    lines += [f"{(label + ':'):<{width}}{value}" for label, value in rows]
    if action_url:
        lines += ["", closing, action_url]
    body = "\n".join(lines)

    html = render_to_string(
        "notifications/request_email.html",
        {
            "urgent": urgent,
            "urgent_note": urgent_note,
            "intro": intro,
            "rows": rows,
            "closing": closing,
            "action_url": action_url,
            "action_label": action_label,
        },
    )
    return EmailContent(subject, body, html=html, urgent=urgent)


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
    if new == Request.Status.APPROVED and req.assigned_to_id:
        # Only an auto-forward can have an assignee this early, so this reads as the
        # requester's own wish being fulfilled.
        lines.append(f"Forwarded to: {_person(req.assigned_to)} to order, as you requested.")
    if new == Request.Status.CHECKED_IN and req.created_item_id:
        lines.append(f"Checked in as: {req.created_item.human_id} · {req.created_item.name}")

    body = "\n".join(lines) + _link(base_url, f"/requests/{req.pk}/")
    return EmailContent(subject, body)


def build_approval_needed(req: Request, *, base_url: str = "") -> EmailContent:
    """Email telling an approver a newly-raised request is waiting for their decision."""
    requester = _person(req.requested_by) if req.requested_by_id else ""
    intro = f"{requester} asks to order:" if requester else "A new request is waiting for approval:"
    rows = [("Request", req.item_name), ("Total", f"{req.total} {req.currency}")]
    if req.vendor_id:
        rows.append(("Vendor", req.vendor.name))
    if req.catalog_number:
        rows.append(("Catalog", req.catalog_number))
    return _request_email(
        subject=f"[LabButler] Approval needed: “{req.item_name}”",
        intro=intro,
        rows=rows,
        closing="See the full details and approve or decline it here:",
        action_url=_url(base_url, f"/requests/{req.pk}/"),
        action_label="See request details",
        urgent=req.is_urgent,
        urgent_note="URGENT — the requester needs a decision as soon as possible.",
    )


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


def build_assignment(req: Request, *, forwarded_by=None, base_url: str = "") -> EmailContent:
    """Email asking a purchase coordinator to place an approved, forwarded request."""
    forwarder = _person(forwarded_by)
    intro = (
        f"{forwarder} has forwarded an approved request to you to order:"
        if forwarder
        else "An approved request has been forwarded to you to order:"
    )
    rows = [("Request", req.item_name)]
    if req.requested_by_id:
        rows.append(("Requested by", _person(req.requested_by)))
    rows.append(("Total", f"{req.total} {req.currency}"))
    if req.vendor_id:
        rows.append(("Vendor", req.vendor.name))
    if req.catalog_number:
        rows.append(("Catalog", req.catalog_number))
    return _request_email(
        subject=f"[LabButler] Please order “{req.item_name}”",
        intro=intro,
        rows=rows,
        closing="See the full details and mark it ordered here:",
        action_url=_url(base_url, f"/requests/{req.pk}/"),
        action_label="See request details",
        urgent=req.is_urgent,
        urgent_note="URGENT — this needs to be ordered as soon as possible.",
    )


def build_welcome(user, lab, set_password_url: str) -> EmailContent:
    """Welcome a newly-added member and hand them a link to set their password.

    The link is passed in fully-formed — generating the reset token is an effect that
    lives in :mod:`apps.notifications.tasks`, keeping this builder pure.
    """
    subject = f"[LabButler] Welcome to {lab.name}"
    lines = [
        f"Hello {user.display_name},",
        "",
        f"You've been added to {lab.name} on LabButler.",
        "",
        "To get started, set a password for your account using the link below:",
        "",
        set_password_url,
        "",
        "For security, this link expires after a while — if it stops working, use the "
        "“Forgot your password?” link on the sign-in page to request a fresh one.",
    ]
    return EmailContent(subject, "\n".join(lines))


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
