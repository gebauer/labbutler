# LabButler

LabButler is a **free, self-hosted lab inventory and order procurement system** — a
Docker-deployable alternative to LabSuit, built for research groups that want to own
their data and run everything locally. No per-seat fees, no vendor shop.

## What it does

- **Inventory** — every physical container is one record with a frozen, human-readable
  ID (e.g. `AGB-04821`) that goes on the barcode and *never changes*. Items carry GHS
  hazard data, hierarchical storage locations (room → fridge → tray), tags, file
  attachments (SDS/MSDS), and lab-defined custom fields.
- **Procurement** — a purchase request flows through approval → ordering → delivery →
  check-in. Checking a delivery in *creates* the inventory item and links back to the
  request, so the paper trail from "we need this" to "it's on shelf 2" is unbroken.
- **Multi-lab, roles & audit** — everything is scoped per lab with per-lab roles and
  permissions, and every transaction lands in an immutable audit trail.
- **Migration** — a spreadsheet importer moves existing LabSuit data over without
  relabelling a single physical container.

## Where to go

<div class="grid cards" markdown>

- **[User guide](user-guide/index.md)** — for lab members and lab managers: working
  with inventory, raising and processing requests, importing data, administering
  members and roles.

- **[Installation & operation](admin-guide/index.md)** — for whoever runs the server:
  deploying with Docker Compose or Coolify, configuration reference, backups and
  maintenance.

- **[Developer guide](dev-guide/index.md)** — for contributors: local development
  setup, architecture, testing, and project conventions.

</div>

## Tech at a glance

Django 5 · PostgreSQL 17 · Celery + Redis · HTMX + Tailwind CSS (server-rendered,
mobile-first) · packaged with uv · deployed via Docker Compose.
