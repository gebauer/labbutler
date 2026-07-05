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


#: Footer for procurement workflow mails, whose frequency members can tune themselves.
_PROCUREMENT_FOOTER = (
    "Sent by LabButler. You can tune which procurement emails you receive under Account settings."
)


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}" if base_url else ""


def _person(user) -> str:
    """Identity line for email bodies: “Ada Lovelace (ada@x.de)”, or just the email."""
    if user is None:
        return ""
    if user.friendly_name and user.email:
        return f"{user.friendly_name} ({user.email})"
    return user.email or user.friendly_name


def _email(
    subject: str,
    *,
    intro: str,
    greeting: str = "",
    rows: list[tuple[str, str]] | None = None,
    sections: list[dict] | None = None,
    closing: str = "",
    action_url: str = "",
    action_label: str = "See details",
    postscript: str = "",
    urgent: bool = False,
    urgent_note: str = "",
    footer: str = "",
) -> EmailContent:
    """Assemble any notification mail (text + HTML) from one shared set of parts.

    ``rows`` are label/value pairs rendered as an aligned table; ``sections`` are
    titled lists (``{"title": ..., "lines": [...]}``) for digest-style mails.
    """
    rows = rows or []
    sections = sections or []
    if urgent:
        subject = subject.replace("[LabButler] ", "[LabButler] URGENT — ", 1)

    lines: list[str] = [urgent_note, ""] if urgent else []
    if greeting:
        lines += [greeting, ""]
    lines.append(intro)
    if rows:
        width = max(len(label) for label, _ in rows) + 2
        lines += [""] + [f"{(label + ':'):<{width}}{value}" for label, value in rows]
    for section in sections:
        lines += ["", f"{section['title']}:"] + [f"  {line}" for line in section["lines"]]
    if action_url:
        lines += ["", closing, action_url] if closing else ["", action_url]
    if postscript:
        lines += ["", postscript]
    body = "\n".join(lines)

    html = render_to_string(
        "notifications/email.html",
        {
            "urgent": urgent,
            "urgent_note": urgent_note,
            "greeting": greeting,
            "intro": intro,
            "rows": rows,
            "sections": sections,
            "closing": closing,
            "action_url": action_url,
            "action_label": action_label,
            "postscript": postscript,
            "footer": footer,
        },
    )
    return EmailContent(subject, body, html=html, urgent=urgent)


def build_status_change(
    req: Request, previous: str, new: str, *, base_url: str = ""
) -> EmailContent:
    """Email announcing that a request moved from ``previous`` to ``new`` status."""
    previous_label = Request.Status(previous).label
    new_label = Request.Status(new).label
    rows = [
        ("Request", req.item_name),
        ("Status", f"{previous_label} → {new_label}"),
        ("Total", f"{req.total} {req.currency}"),
    ]
    if req.vendor_id:
        rows.append(("Vendor", req.vendor.name))
    if req.po_number:
        rows.append(("PO #", req.po_number))
    if new == Request.Status.APPROVED and req.assigned_to_id:
        # Only an auto-forward can have an assignee this early, so this reads as the
        # requester's own wish being fulfilled.
        rows.append(("Forwarded to", f"{_person(req.assigned_to)} to order, as you requested."))
    if new == Request.Status.CHECKED_IN and req.created_item_id:
        rows.append(("Checked in as", f"{req.created_item.human_id} · {req.created_item.name}"))
    return _email(
        f"[LabButler] Request “{req.item_name}” is now {new_label}",
        intro=f"A request you are involved in is now {new_label}:",
        rows=rows,
        closing="See the full details here:",
        action_url=_url(base_url, f"/requests/{req.pk}/"),
        action_label="See request details",
        footer=_PROCUREMENT_FOOTER,
    )


def build_approval_needed(req: Request, *, base_url: str = "") -> EmailContent:
    """Email telling an approver a newly-raised request is waiting for their decision."""
    requester = _person(req.requested_by) if req.requested_by_id else ""
    intro = f"{requester} asks to order:" if requester else "A new request is waiting for approval:"
    rows = [("Request", req.item_name), ("Total", f"{req.total} {req.currency}")]
    if req.vendor_id:
        rows.append(("Vendor", req.vendor.name))
    if req.catalog_number:
        rows.append(("Catalog", req.catalog_number))
    return _email(
        f"[LabButler] Approval needed: “{req.item_name}”",
        intro=intro,
        rows=rows,
        closing="See the full details and approve or decline it here:",
        action_url=_url(base_url, f"/requests/{req.pk}/"),
        action_label="See request details",
        urgent=req.is_urgent,
        urgent_note="URGENT — the requester needs a decision as soon as possible.",
        footer=_PROCUREMENT_FOOTER,
    )


def build_daily_digest(
    lab, pending_approvals: list, recent_updates: list, today: date, *, base_url: str = ""
) -> EmailContent:
    """A once-a-day per-member digest: requests awaiting their approval + their updates."""
    sections = []
    if pending_approvals:
        sections.append(
            {
                "title": "Awaiting your approval",
                "lines": [f"{r.item_name}  ({r.total} {r.currency})" for r in pending_approvals],
            }
        )
    if recent_updates:
        sections.append(
            {
                "title": "Your requests, recently updated",
                "lines": [
                    f"{r.item_name}  →  {Request.Status(r.status).label}" for r in recent_updates
                ],
            }
        )
    return _email(
        f"[LabButler] {lab.name}: daily procurement summary",
        intro=f"Procurement summary for {lab.name}, {today:%Y-%m-%d}.",
        sections=sections,
        closing="Act on them here:",
        action_url=_url(base_url, "/requests/"),
        action_label="Open the request list",
        footer=_PROCUREMENT_FOOTER,
    )


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
    return _email(
        f"[LabButler] Please order “{req.item_name}”",
        intro=intro,
        rows=rows,
        closing="See the full details and mark it ordered here:",
        action_url=_url(base_url, f"/requests/{req.pk}/"),
        action_label="See request details",
        urgent=req.is_urgent,
        urgent_note="URGENT — this needs to be ordered as soon as possible.",
        footer=_PROCUREMENT_FOOTER,
    )


def build_welcome(user, lab, set_password_url: str) -> EmailContent:
    """Welcome a newly-added member and hand them a link to set their password.

    The link is passed in fully-formed — generating the reset token is an effect that
    lives in :mod:`apps.notifications.tasks`, keeping this builder pure.
    """
    return _email(
        f"[LabButler] Welcome to {lab.name}",
        greeting=f"Hello {user.display_name},",
        intro=f"You've been added to {lab.name} on LabButler — the lab's shared "
        "inventory and ordering tool.",
        closing="To get started, set a password for your account:",
        action_url=set_password_url,
        action_label="Set your password",
        postscript="For security, this link expires after a while — if it stops working, "
        "use the “Forgot your password?” link on the sign-in page to request a fresh one.",
    )


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
        return f"{item.expiration_date:%Y-%m-%d}  {item.human_id}  {item.name}  ({location})"

    sections = []
    if expired:
        sections.append({"title": "Already expired", "lines": [_row(i) for i in expired]})
    if expiring:
        sections.append(
            {
                "title": f"Expiring within {days_ahead} days",
                "lines": [_row(i) for i in expiring],
            }
        )
    return _email(
        subject,
        intro=f"Expiry report for {lab.name}, generated {today:%Y-%m-%d}.",
        sections=sections,
        closing="Review them in the inventory:",
        action_url=_url(base_url, "/inventory/"),
        action_label="Open the inventory",
    )
