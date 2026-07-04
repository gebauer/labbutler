# Architecture

## Repository layout

```
labbutler/                # Django project: settings (env-driven), urls, celery,
│                         # dashboard builder, healthz, static/
└── apps/                 # one Django app per domain
    ├── tenancy/          # User, Lab, Membership, Role, Permission + scoping
    ├── inventory/        # Item, Location, Tag, FieldDefinition/Preset, HazardStatement
    ├── procurement/      # Request workflow, Budget, Vendor, ShippingAddress
    ├── imports/          # LabSuit profile + generic mapper, dry-run preview
    ├── notifications/    # status emails + daily digests (Celery)
    ├── attachments/      # generic file attachments (items & requests)
    ├── comments/         # generic comment threads (items & requests)
    └── audit/            # append-only AuditEntry
templates/                # project-level Django templates (HTMX + Tailwind)
scripts/pg.sh             # project-local dev Postgres helper
```

Tests live in each app under `<app>/tests/`, mirroring the module under test.

## Multi-tenancy & permissions

Everything hangs off **`Lab`** (`apps/tenancy/models.py`) — the tenant and scoping
anchor. A **`Membership`** ties a user to a lab and carries **`Role`**s; roles are
per-lab, editable sets of **`Permission`**s from a fixed, installation-wide
catalog (`apps/tenancy/catalog.py`, seeded by a data migration; template roles are
cloned into each new lab).

The rules of engagement:

- The current lab is kept in the session; `apps/tenancy/scoping.py` resolves it,
  a context processor exposes it to templates, and the nav renders a lab switcher.
- Views check access with the `require_permission("<code>")` decorator; code asks
  `user.can(lab, "<code>")`. **Fail closed** — no permission, no action, and
  querysets are always filtered by `lab=request.lab`.
- Never trust a pk from the URL alone: every object lookup includes the lab
  (`get_object_or_404(Model, pk=pk, lab=request.lab)`).

## Frozen item IDs

`Lab.allocate_item_id()` reserves the next `PREFIX-NNNNN` under a
`select_for_update` row lock, so concurrent check-ins and imports can't collide.
The invariant, inherited from LabSuit's reclassification bug, is absolute: **a
human ID is assigned once and never recomputed from any mutable field.** Imported
items instead keep their LabSuit serial as the frozen ID.

## The procurement state machine

`apps/procurement/services.py` is the single source of truth for the request
workflow. `TRANSITIONS` is a table of moves (action, from-statuses, target status,
required permission); views and templates ask `may_perform` /
`available_transitions` instead of hard-coding status logic, and
`perform_transition` applies a move atomically — status change, side effects,
audit entry, and notification enqueue in one transaction.

Special flows live beside it as explicit functions rather than table entries:
`self_approve` (posts an on-the-record comment), `forward` (assign to a purchase
coordinator), and `receive` (a dialog with two terminal outcomes: create the
inventory item and check in, or record an untracked receipt). Item creation on
check-in is `_create_item_from`, which copies the request's commercial and hazard
data onto the new item and back-links it via `Request.created_item`.

## Audit

`AuditEntry.record(lab=…, actor=…, action=…, target=…, changes=…)` writes an
append-only entry; there is no update/delete path. Every mutation — CRUD and
workflow moves alike — must record one. Actions are dotted strings like
`procurement.request_approve` or `lab.supplier_created`.

## Notifications

`apps/notifications/` separates **pure email builders** (`emails.py`) from
**Celery tasks** (`tasks.py`). Domain code never sends mail directly: it enqueues
via `transaction.on_commit(...)`, so an email can never announce a transaction
that rolled back. Daily digests (expiry, procurement) run on Celery beat.

## Imports

`apps/imports/` is two-phase everywhere: `build_plan` (or `build_generic_plan`)
parses the workbook into a `ParsedRow`/`ImportPlan` **without touching the
database** — this is what the dry-run preview renders — and `commit` applies a
plan. Parsers for the messy real-world formats (prices, dates, locations, the
LabSuit TAGS soup) live in `parsers.py` as pure functions; the LabSuit profile
upserts on the legacy serial, the generic path always creates and mints fresh IDs.

## Frontend

Server-rendered templates with HTMX for the dynamic parts (live search partials,
inline workflow actions) and Tailwind for styling; htmx and Sortable are vendored,
so there is no runtime CDN dependency. Templates live project-level in
`templates/`, mobile-first — tables collapse to cards on small screens.

## Design habits worth keeping

- **Pure core, effectful edges** — parsing, planning, email building, and the
  transition table are pure and unit-testable; I/O happens in views, tasks, and
  `commit` functions.
- **Single source of truth** — the permission catalog, the transition table, the
  location tree helpers: one place defines the behaviour, everything else asks it.
- **No N+1 on trees** — `Location.tree_for_lab` / `attach_path_names` build the
  hierarchy from one query; don't walk `parent` links in loops or templates.
