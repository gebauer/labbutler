# User guide overview

This guide is for people *using* LabButler day to day: lab members at the bench, the
people who approve and place orders, and lab managers who administer members and
settings. (If you are looking for how to install the server, see
[Installation & operation](../admin-guide/index.md).)

## The core ideas

A few concepts run through everything, so it is worth meeting them once up front.

### Labs

A LabButler installation can host several **labs**. Each lab is a fully separate
world: its own inventory, requests, members, roles, suppliers, and budgets. Most
installations have exactly one lab, and then you will never notice this layer. If you
belong to more than one lab, a **lab switcher** in the navigation bar selects which
lab you are working in.

### Frozen item IDs

Every inventory item has a human-readable identifier like `AGB-04821` — a per-lab
prefix plus a running number. This ID is assigned **once, when the item is created,
and never changes**, no matter how the item is later renamed, moved, or reclassified.
It is what you print on the physical label, so a container labelled years ago can
always be found. Items migrated from LabSuit keep their original LabSuit serial as
their frozen ID, so nothing needs relabelling.

### Roles and permissions

What you can see and do is controlled by the **roles** your lab manager has given
you. Every action in this guide names the permission it needs (for example,
*approving a request requires `approve_request`*). If a button or menu item described
here is missing for you, you simply don't hold that permission — ask your lab
manager. The full catalog is listed in
[Lab administration](lab-administration.md#permissions).

New labs start with four editable roles:

| Role | Meant for |
|---|---|
| **Lab manager** | Full control: everything, including members, roles and settings |
| **Member** | Everyday lab work: manage inventory, raise requests, check in/out |
| **Viewer** | Read-only access to inventory and requests |
| **Purchase coordinator** | Order-responsible staff: sees requests, places orders |

### The audit trail

Every create, edit, delete, and workflow move is recorded in an append-only audit
log — who did what, when, and what changed. Nothing in the audit trail can be edited
or deleted afterwards.

## Chapters

- [Getting started](getting-started.md) — signing in, the dashboard, your account.
- [Inventory](inventory.md) — items, search, locations, tags, hazard data, labels.
- [Procurement requests](procurement.md) — the request workflow from wish to shelf.
- [Importing data](importing.md) — migrating from LabSuit or other spreadsheets.
- [Lab administration](lab-administration.md) — members, roles, suppliers, budgets.
- [Notifications](notifications.md) — the emails LabButler sends and how to tune them.
