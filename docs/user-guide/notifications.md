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

## Expiry digest

Once a day, members who hold `manage_inventory` receive a per-lab digest of items
that are **expired or expiring soon** (within a configurable look-ahead window,
30 days by default), based on each item's expiration date.

## Welcome & password emails

- New members receive a **welcome email with a set-password link** when they are
  added to a lab.
- The **Forgot password?** flow emails a reset link. Both links expire after a
  configurable number of days (3 by default).

## Choosing what you receive

Under **Account settings → Notifications** you can switch procurement emails on or
off **per lab**. Only categories you can act on are shown — e.g. approval
notifications only appear if you can approve requests.
