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

## Roles and permissions

Roles are **per lab and fully editable**: a role is just a named set of
permissions, and a member can hold several roles (their permissions add up). New
labs start with clones of the four template roles (Lab manager, Member, Viewer,
Purchase coordinator) — rename them, change their permissions, delete them, or
create your own under **Manage → Roles**.

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
| `check_in` | Receive deliveries / check items into inventory |
| `check_out` | Consume/remove items from inventory |
| `manage_lab` | Members, roles, suppliers, budgets, addresses, lab settings |

Permission checks **fail closed**: no permission, no button, and the underlying
action is refused server-side too.

## Suppliers

**Manage → Suppliers** is the lab's vendor list, referenced by items and requests.
A supplier is just a name and can also be quick-created inline while filling in a
request.

## Budgets (Kostenstellen)

**Manage → Budgets** defines the cost centres requests are charged to — each has a
number (Kostenstelle), a name, and optionally an owning member. One budget can be
marked as the **default**, preselected on new requests. Budget numbers are unique
within the lab, giving you rough per-KST expense reporting over the request
history.

## Shipping addresses

**Manage → Shipping addresses** holds the delivery addresses selectable on
requests; one can be the default.

## Locations, custom fields

Storage locations (**Manage → Locations**) and custom item fields
(**Manage → Custom fields**) are described in the
[Inventory chapter](inventory.md#locations); note that managing these requires
`manage_inventory` rather than `manage_lab`.

## Lab settings

**Manage → Settings** holds the lab-wide defaults:

- **Item ID prefix** — the frozen prefix for new item IDs (e.g. `AGB` →
  `AGB-04821`). Chosen when the lab is created.
- **Default VAT rate** — used for the automatic tax calculation on requests
  (19% by default).
- **Default currency** — preselected on new requests.

## Superuser: "View as" impersonation

Installation superusers can temporarily **view the app as another user** to verify
role setups ("can the new student really not see budgets?"). This is off unless the
server administrator has
[explicitly enabled it](../admin-guide/configuration.md#impersonation), and every
action taken while impersonating is audit-logged with the real superuser's
identity.
