# Notifications

LabButler keeps people informed by email — sparingly, and only about things they
can act on. All mail is sent in the background, so the app never blocks on a slow
mail server.

## Request status emails

When a request moves through the workflow (approved, rejected, ordered, received,
checked in, cancelled), the people involved — the **requester**, the **approver**,
and the **assigned purchase coordinator** — are emailed about the change. Being
forwarded a request also notifies the new assignee. Emails link straight to the
request (when the server has a
[base URL configured](../admin-guide/configuration.md)).

## Daily procurement digest

Instead of a mail per event, pending work is also summarised once a day: approvers
get outstanding approvals, requesters get updates on their open requests. The send
hour is [configured by the administrator](../admin-guide/configuration.md).

## Weekly expiry report

Once a week (Monday mornings by default), every member receives a personal report
of items that are **expired or expiring soon**, based on each item's expiration
date. Each member tunes the report under **Account settings → Notifications**:

- **What it contains** — *all* expired items every week, only items that **newly
  expired since the last report** (the default), or **never** (switches the report
  off).
- **Only items I own** — limit the report to items where you are set as the owner.
  Members without the `view_inventory` permission always get only their own items.
- **Advance warning** — how far ahead you're warned about items expiring soon:
  7, 14, or 30 days (default). In the "only newly expired" mode, the expiring-soon
  section likewise lists just the items that entered your warning window since the
  previous report.

A member with nothing to report simply gets no email that week.

## Welcome & password emails

- New members receive a **welcome email with a set-password link** when they are
  added to a lab.
- The **Forgot password?** flow emails a reset link. Both links expire after a
  configurable number of days (3 by default).

## Choosing what you receive

Under **Account settings → Notifications** you can switch procurement emails on or
off and tune the weekly expiry report **per lab**. Procurement categories only
appear if you can act on them — e.g. approval notifications only appear if you can
approve requests; the expiry report settings are available to every member.
