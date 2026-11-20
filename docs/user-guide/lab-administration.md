# Lab administration

Everything in this chapter lives under **Manage** in the navigation bar and
requires the `manage_lab` permission (held by the *Lab manager* template role).

## Members

**Manage → Members** lists everyone in the lab with their roles.

- **Adding a member** creates their account (if it doesn't exist yet) and emails
  them a **welcome message with a set-password link** — you never handle their
  password. The link's validity period is
  [configurable](../admin-guide/configuration.md) (3 days by default).
- **Editing** a membership changes which roles the member holds.
- **Removing** a member takes away their access to this lab only; in a multi-lab
  installation their other memberships are untouched.

Email addresses are treated case-insensitively.

!!! note "There is always a manager"
    A change that would leave the lab without anyone holding `manage_lab` — removing
    your own manager role, editing or deleting the only manager role, removing the
    last manager — is refused. Give someone else the right first.

### Join link — let people ask to join

Instead of typing in every address, you can share a **join link** (e.g. in the lab
chat or on the group wiki). Under **Manage → Members → Join link**, press **Create
join link** and copy it.

1. Whoever opens the link enters their name, email address and an optional message.
2. LabButler emails them a confirmation link. Only **confirmed** requests reach you, so
   typos and addresses typed in by someone else never show up.
3. Everyone who can manage the lab gets an email, the request appears at the top of
   **Manage → Members** and as a **Join requests** card on the dashboard.
4. **Approve** it with the roles to grant (the lab's *Member* role is preselected) —
   new people get the usual welcome email with a set-password link, people who already
   have an account are told they can sign in. Or **Reject** it; they get a short,
   neutral email.

Nobody gets any access without your approval. **New link** replaces the link (the old
one stops working at once — use it if the link leaked somewhere it shouldn't be);
**Turn off** disables it. Unconfirmed requests are deleted after 7 days and decided
ones after 90 days; each decision stays in the audit log.

## Roles and permissions

Roles are **per lab and fully editable**: a role is just a named set of
permissions, and a member can hold several roles — **their permissions simply add
up** (there are no deny rules, so extra roles only ever grant more). New labs
start with clones of the four template roles (Lab manager, Member, Viewer,
Purchase coordinator) — rename them, change their permissions, delete them, or
create your own under **Manage → Roles**.

Note that the *Purchase coordinator* role is a convention, not a mechanism: what
makes someone appear in the
[forward-to list](procurement.md#forwarding-to-a-purchase-coordinator) is holding
the `accept_forwards` permission, from whichever role. `place_order` and
`accept_forwards` are deliberately separate: in a lab where *everyone* may order
but only a few people (say, the technicians) handle forwarded requests, give
`place_order` to your standard role and `accept_forwards` only to the
coordinators — the forward list then stays short. People can of course hold the
coordinator role alongside *Member* or any other role.

### Permissions

The permission catalog is fixed and installation-wide:

| Permission | Grants |
|---|---|
| `view_inventory` | See inventory |
| `view_requests` | See requests |
| `manage_inventory` | Create/edit/delete items, custom fields, presets, locations, tags |
| `import_inventory` | Run spreadsheet imports |
| `create_request` | Raise a request |
| `approve_request` | Approve/reject requests |
| `self_approve` | Approve your *own* requests (posts an on-the-record comment) |
| `place_order` | Mark approved requests as ordered |
| `accept_forwards` | Receive forwarded requests — appear in the forward-to list |
| `check_in` | Receive deliveries / check items into inventory |
| `check_out` | Consume/remove items from inventory |
| `manage_lab` | Members, roles, suppliers, budgets, addresses, lab settings |

Permission checks **fail closed**: no permission, no button, and the underlying
action is refused server-side too.

## Suppliers

**Manage → Suppliers** is the lab's vendor list, referenced by items and requests.
A supplier is just a name and can also be quick-created inline while filling in a
request.

Suppliers, budgets and shipping addresses that are still used by requests or items
can't be deleted — that would erase them from those records' history. Merge duplicate
suppliers (**Merge suppliers**) or rename the record instead.

## Budgets (Kostenstellen)

**Manage → Budgets** defines the cost centres requests are charged to — each has a
number (Kostenstelle), a name, and optionally an owning member. One budget can be
marked as the **default**, preselected on new requests. Budget numbers are unique
within the lab, giving you rough per-KST expense reporting over the request
history.

## Shipping addresses

**Manage → Shipping addresses** holds the delivery addresses selectable on
requests; one can be the default.

## Locations, custom fields, field presets

Storage locations (**Manage → Locations**), custom item fields
(**Manage → Custom fields**) and their named bundles (**Manage → Field presets**)
are described in the [Inventory chapter](inventory.md#locations); note that
managing these requires `manage_inventory` rather than `manage_lab`.

## Lab settings

**Manage → Settings** holds the lab-wide defaults:

- **Item ID prefix** — the frozen prefix for new item IDs (e.g. `AGB` →
  `AGB-04821`). Chosen when the lab is created; keep it **short (around 3
  letters)** so IDs print well on small container labels.
- **Default VAT rate** — used for the automatic tax calculation on requests
  (19% by default).
- **Default currency** — preselected on new requests.

## Danger zone: start over

At the bottom of **Admin** are two buttons for wiping data, typically before a fresh
LabSuit import. Each opens a page that lists exactly what will be deleted; you confirm
by typing the lab's name. Neither can be undone — take a database backup first (see
the maintenance guide). The audit log keeps a record of who deleted what and how much.

- **Delete inventory…** removes every item (with its attachments, comments and scan
  history), all locations, and the tags no request uses. Requests, suppliers, budgets,
  custom fields and members stay. Item IDs that were used are never reissued, and a
  LabSuit re-import brings items back under their original IDs, so existing labels
  stay valid.
- **Delete requests…** removes every request — open ones and the order history,
  including imported LabSuit orders — with their purchase-order forms, attachments and
  comments. The inventory, suppliers, budgets and shipping addresses stay.

## Superuser: "View as" impersonation

Installation superusers can temporarily **view the app as another user** to verify
role setups ("can the new student really not see budgets?"). This is off unless the
server administrator has
[explicitly enabled it](../admin-guide/configuration.md#impersonation), and every
action taken while impersonating is audit-logged with the real superuser's
identity.
