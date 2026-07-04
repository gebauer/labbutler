# LabButler

A free, self-hosted, Docker-deployable alternative to LabSuit for **lab inventory** and
**order procurement**. Built for a single research institute that wants to leave LabSuit,
keep its data, and run everything locally — no per-seat fees, no vendor shop.

> Status: **v1.0 — first release.** The conceptual design lives in
> [`Buildv1.MD`](Buildv1.MD); this README covers what the software is and how to run it.

**📖 Full documentation** (user guide, installation & operation, developer guide):
<https://gebauer.github.io/labbutler/> — sources in [`docs/`](docs/), built with MkDocs
Material and deployed to GitHub Pages on push to `main`.

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
| Deployment | **Docker Compose** (`web`, `db`, `worker`, `beat`, `broker`, media volume) |

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
(Postgres), `worker` + `beat` (Celery for status emails and the daily expiry digest),
`broker` (Redis), and a **media volume**. Email is sent over SMTP.

```bash
cp .env.example .env        # set SECRET_KEY, DB creds, SMTP, ALLOWED_HOSTS, CSRF origins
docker compose up -d --build
docker compose run --rm web python manage.py bootstrap_lab   # first run: superuser + lab
```

- The `web` service **runs migrations on start**, and static assets (Tailwind CSS plus
  the vendored htmx/Sortable) are **built and collected at image build time** and served
  by WhiteNoise — no separate static step, no CDN.
- Put a TLS-terminating reverse proxy in front and forward `X-Forwarded-Proto`; the app
  then enforces HTTPS redirect, HSTS and secure cookies (tunable via `DJANGO_SECURE_*`).
  Set `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` to your domain.
- Health probe: `GET /healthz` returns `200 ok` when the database is reachable (the `web`
  container's health check uses it).
- **Login brute-force protection** is on by default (django-axes): a client IP + username
  is locked out after `AXES_FAILURE_LIMIT` failed sign-ins for `AXES_COOLOFF_HOURS`.
  **Set `AXES_IPWARE_PROXY_COUNT` to the number of proxies** in front so the real client
  IP is used, not the proxy's.

All configuration is via environment variables (`.env`) — **no secrets in the repo**.
Database migrations are append-only and reversible.

### On Coolify

LabButler drops into [Coolify](https://coolify.io) cleanly — it's 12-factor and
proxy-ready, and Coolify's Traefik terminates TLS and forwards `X-Forwarded-Proto` /
`X-Forwarded-For`, which the app already trusts.

1. **New Resource → Docker Compose**, pointed at this repo (uses `docker-compose.yml`:
   `web`, `db`, `broker`, `worker`, `beat`). Assign your domain to the **`web`** service.
2. Set these **environment variables** in Coolify (it injects them into the compose):

   | Variable | Value |
   |---|---|
   | `DJANGO_SECRET_KEY` | long random (`python -c "import secrets;print(secrets.token_urlsafe(50))"`) |
   | `DJANGO_DEBUG` | `false` |
   | `DJANGO_ALLOWED_HOSTS` | `labbutler.your.domain` |
   | `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://labbutler.your.domain` |
   | `LABBUTLER_BASE_URL` | `https://labbutler.your.domain` |
   | `POSTGRES_PASSWORD` / `DATABASE_URL` | a **strong** password (used in both) |
   | `AXES_IPWARE_PROXY_COUNT` | `1` — Coolify's proxy is the one hop; required so lockouts use the real client IP |
   | `EMAIL_*`, `DEFAULT_FROM_EMAIL` | your SMTP details |

3. **Deploy.** `web` migrates on start; static assets are already in the image.
4. **First run only:** open the `web` container's terminal in Coolify and run
   `python manage.py bootstrap_lab` (creates the superuser + first lab).
5. Coolify persists the `pgdata` and `media` volumes across redeploys — **back up `pgdata`**.

Notes: if you ever hit an HTTPS **redirect loop**, set `DJANGO_SECURE_SSL_REDIRECT=false`
(Coolify already redirects http→https at the edge). To use Coolify's **managed** Postgres/
Redis instead, point `DATABASE_URL` / `CELERY_BROKER_URL` at them and drop the `db` /
`broker` services.

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
    ├── notifications/    # status emails + daily expiry digest (Celery)
    ├── comments/         # generic comment threads on items & requests
    └── audit/            # immutable AuditEntry
```

---

## License

TBD.
