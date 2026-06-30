# LabButler — Build TODO

Living checklist for the MVP build. Keep this current: check items off as they land,
add notes under a step when decisions are made. Each major step ends in a commit (no push).

Spec: [Buildv1.MD](Buildv1.MD) · Stack: Django 5 / Postgres 17 / Celery+Redis / HTMX / Tailwind / uv.

## Decisions / conventions
- `sample_data/` is git-ignored (contains real PII). Used as a local import fixture only.
- Commit after every major step; never push unless asked.
- Multi-lab from the start, collapsible to one `Lab`.

## Steps

- [x] **0. Repo hygiene** — `.gitignore` (exclude sample_data, venv, secrets). _(commit: b718e9c)_
- [x] **1. Baseline docs committed** — Buildv1.MD, README.md, CLAUDE.md. _(commit: e97505e)_
- [x] **2. Project scaffold** — `pyproject.toml` (uv), Django project `labbutler/`, settings, the 5 apps
      (`tenancy`, `inventory`, `procurement`, `imports`, `audit`), `manage.py`. Runnable empty skeleton.
      Custom `tenancy.User` (email login). `scripts/pg.sh` project-local Postgres (port 55432).
      Verified: migrate OK, runserver serves home/login/admin, ruff clean.
- [ ] **3. Tooling & infra** — `.env.example`, settings via env, pytest + ruff config, Docker Compose
      (`web`/`db`/`worker`/`broker` + media volume), Tailwind/HTMX wiring, Celery app.
- [ ] **4. CLAUDE.md commands** — fill the `[bracketed]` command placeholders (uv run pytest/ruff/migrate…).
- [ ] **5. Data models** — tenancy (Lab/Membership/Role/Permission), inventory (Item/Location/Tag/
      FieldDefinition/FieldPreset/HazardStatement), procurement (Request/Budget/Vendor/ShippingAddress),
      audit (AuditEntry). Migrations. `user.can(lab, perm)` helper. `bootstrap_lab` command.
- [ ] **6. LabSuit importer** — LabSuit profile + generic mapper, parsers (price/date/location/TAGS→hazard),
      dry-run preview, dedup on legacy serial. Tested against `sample_data/`.
- [ ] **7. Inventory UI** — list/detail/edit, responsive (HTMX + Tailwind), search.
- [ ] **8. Procurement UI** — request workflow state machine, approvals, ordering, check-in→creates item.
- [ ] **9. Notifications** — SMTP: status changes + expiry digest (Celery beat).

## Notes / open spec items (defer until relevant)
- Shipping cost inside tax base? (assume yes)
- Multi-currency reporting: per-currency vs converted.
- Exact split of `approve_request` / `place_order` / order-responsible assignment.
