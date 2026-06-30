# LabButler

A free, self-hosted, Docker-deployable alternative to LabSuit for **lab inventory** and
**order procurement**. Built for a single research institute that wants to leave LabSuit,
keep its data, and run everything locally — no per-seat fees, no vendor shop.

> Status: **early development (MVP in progress).** The conceptual design lives in
> [`Buildv1.MD`](Buildv1.MD); this README covers what the software is and how to run it.

---

## What it does

LabButler gives a lab two things in one shared, searchable, audited record:

- **Inventory** — every physical container is one record with a frozen, human-readable ID
  (e.g. `AGB-04821`) that goes on the barcode and *never changes*, even when an item is
  reclassified. Items carry hazard data (GHS H/P/EUH codes, signal word, WGK, storage
  class), hierarchical locations (room → fridge → tray), tags, attachments (SDS/MSDS), and
  lab-defined custom fields.
- **Procurement** — a request flows through approval → ordering → delivery → check-in. On
  check-in the request *creates* the inventory item and links back to it. Costs (with
  auto-calculated VAT) are charged to a budget / cost centre (Kostenstelle) for rough
  per-KST expense reporting.

Everything is **multi-lab capable** but collapses to a single lab at zero cost, with
**per-lab roles & permissions** and an **immutable audit trail** of every transaction. A
spreadsheet importer migrates existing LabSuit data without relabelling any physical
container.

See [`Buildv1.MD`](Buildv1.MD) for the full design rationale and data model.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | **Django 5.x** (Python 3.11) |
| Database | **PostgreSQL 17** (JSONB custom fields, GIN-indexed) |
| Async / scheduled | **Celery** + **Redis** (expiry digests, email, large imports) |
| Frontend | Server-rendered Django templates + **HTMX**, styled with **Tailwind CSS** (mobile-first, responsive) |
| Packaging / env | **uv** (`pyproject.toml` + `uv.lock`) |
| Deployment | **Docker Compose** (`web`, `db`, `worker`, `broker`, media volume) |

The UI is **responsive and mobile-first**: phones/tablets at the bench (check-in/out,
lookups, scanning), full-width monitors for management, import, and reporting. Tables
collapse to stacked cards on small screens.

---

## Running locally (development)

Dev runs natively (no Docker) for a fast inner loop. You need:

- **[uv](https://docs.astral.sh/uv/)** — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **PostgreSQL 17** — server binaries (a project-local instance on a non-default port is
  used so it never clashes with a system Postgres)
- **Redis** — `sudo apt install redis-server && sudo service redis-server start`
- **Node + npm** — only for building Tailwind CSS

```bash
# 1. Install Python deps into a project-local .venv
uv sync

# 2. Configure environment (copy and edit)
cp .env.example .env

# 3. Start Postgres + Redis (see scripts/ for the local Postgres helper)

# 4. Apply migrations and create the first admin + lab
uv run manage.py migrate
uv run manage.py bootstrap_lab      # guided first-run: superuser + initial Lab + template roles

# 5. Build CSS (watch mode in a second terminal)
npm install
npm run dev          # tailwind --watch

# 6. Run the app and the worker
uv run manage.py runserver
uv run celery -A labbutler worker -l info     # in another terminal
```

App is then at <http://localhost:8000>.

### Common commands

| Task | Command |
|---|---|
| Run tests | `uv run pytest` |
| Lint / format | `uv run ruff check .` / `uv run ruff format .` |
| Make migrations | `uv run manage.py makemigrations` |
| Django shell | `uv run manage.py shell` |
| Add a dependency | `uv add <package>` |

---

## Deploying (production)

Production runs the whole stack via **Docker Compose**: `web` (Django/Gunicorn), `db`
(Postgres), `worker` (Celery), `broker` (Redis), and a **media volume** for attachments.
Email is sent over SMTP.

```bash
cp .env.example .env        # set SECRET_KEY, DB creds, SMTP, ALLOWED_HOSTS
docker compose up -d --build
docker compose run --rm web manage.py migrate
docker compose run --rm web manage.py bootstrap_lab
```

All configuration is via environment variables (`.env`) — **no secrets in the repo**.
Database migrations are append-only and reversible.

---

## Importing LabSuit data

The importer is what makes LabButler usable on day one. Two paths:

- A built-in **LabSuit profile** that understands the export layout (control columns,
  `Import Instructions` sheet, the messy `TAGS` soup).
- A generic **column-mapper** for other sources.

It parses the real-world quirks — mixed price formats (`18.80EUR`, `EUR 109.00`,
`$ 500.00`), European `DD-MM-YYYY` dates, dirty 3-level locations, GHS codes split out of
`TAGS` into the hazard catalog — and shows a **dry-run preview** ("1,840 OK, 28 warnings,
6 errors") before committing. Imported items keep their original LabSuit serial as their
frozen identifier, so **no container needs relabelling**.

German CSV exports (semicolon-delimited, comma decimals, latin-1) are supported.

---

## Project layout

```
labbutler/
├── Buildv1.MD            # conceptual spec & MVP outline (design rationale)
├── README.md             # this file
├── CLAUDE.md             # engineering guidance for contributors / AI assistants
├── pyproject.toml        # deps & tooling (managed by uv)
├── docker-compose.yml    # production stack
├── manage.py
├── labbutler/            # Django project (settings, celery, urls)
└── apps/
    ├── tenancy/          # Lab, Membership, Role, Permission
    ├── inventory/        # Item, Location, Tag, FieldDefinition, HazardStatement
    ├── procurement/      # Request workflow, Budget, Vendor, ShippingAddress
    ├── imports/          # LabSuit profile + generic mapper, dry-run preview
    └── audit/            # immutable AuditEntry
```

*(Layout is provisional until the scaffold lands; it follows the data model in the spec.)*

---

## License

TBD.
