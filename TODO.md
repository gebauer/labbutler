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
- [x] **3. Tooling & infra** — `.env.example`, settings via env, pytest + ruff config, Docker Compose
      (`web`/`db`/`worker`/`broker` + media volume), multistage `Dockerfile`, Tailwind/HTMX wiring,
      Celery app. Tailwind builds; pytest (2 tests) + ruff green. _Docker build unverified locally
      (no daemon)._
- [x] **4. CLAUDE.md commands** — filled command placeholders + real project-structure section.
- [x] **5. Data models** — tenancy (Lab/Membership/Role/Permission), inventory (Item/Location/Tag/
      FieldDefinition/FieldPreset/HazardStatement), procurement (Request/Budget/Vendor/ShippingAddress),
      audit (AuditEntry). Migrations + seeded permission catalog & template roles. `user.can(lab, perm)`,
      `Lab.allocate_item_id()` (frozen IDs), `Request.recalculate_totals()` (auto-VAT), append-only audit.
      `create_lab` (clones template roles) + `bootstrap_lab` command. Admin registered. 11 tests green.
- [x] **6. LabSuit importer** — parsers (price/date/location/TAGS→hazard), LabSuit workbook profile,
      two-phase `build_plan` (dry-run preview) + `commit` (upsert on legacy serial, location hierarchy,
      custom-field pool, tags/hazards/vendor/owner). `import_labsuit` command. Verified on real export:
      **1,889 OK, 33 warnings, 0 errors**. 43 tests green, ruff clean.
      _Generic column-mapper (non-LabSuit sources) still TODO — Phase: see step 6b._
- [x] **6b. Generic import mapper** — pure core (`imports/generic.py`: column reader,
      target registry, header guesser, mapping-driven `build_generic_plan`) reusing the
      LabSuit `ParsedRow`/`ImportPlan`/`commit`. `commit` now mints a fresh frozen
      `human_id` for serial-less generic rows (LabSuit upsert path unchanged). 4-step
      web wizard (upload → map columns → dry-run preview → commit), session-backed,
      gated on `import_inventory`, isolated-MEDIA upload. 10 new tests; 66 total green.
      _CSV input still TODO (openpyxl is xlsx-only); generic imports always create (no
      serial-based dedup)._
- [x] **7. Inventory UI** — list/detail/edit/delete + free-text & tag search (HTMX live partial),
      lab scoping via session (`tenancy.scoping`, permission decorator, context processor +
      nav lab-switcher). Create allocates a frozen `human_id`; edits/deletes write audit entries.
      Custom fields shown read-only on detail (editing deferred). 14 view tests; 56 total green,
      ruff clean. _Done before 6b (UI foundation first, per decision)._
- [x] **8. Procurement UI** — request workflow as a single-source state machine
      (`procurement/services.py`: `TRANSITIONS` table + `may_perform`/`available_transitions`/
      `perform_transition`). Moves: approve/reject → order → deliver → check-in (creates the
      inventory item, links `created_item`, redirects to it); cancel by requester or manager.
      Each move re-checks its permission and fails closed; audit entry per transition.
      Filterable list, detail with contextual action buttons (+optional PO#), create/edit
      (edit only while 'Requested'), auto VAT/total via `recalculate_totals`. Requests nav
      link gated on `view_requests`. 11 new tests; 77 total green, ruff clean.
- [x] **9. Notifications** — `apps/notifications/` app: pure email builders (`emails.py`) +
      Celery tasks (`tasks.py`). Request status changes email the requester/approver/assignee,
      enqueued via `transaction.on_commit` from `perform_transition`. Daily per-lab expiry
      digest (expired + expiring within `EXPIRY_DIGEST_DAYS`) to members who can
      `manage_inventory`, wired to `CELERY_BEAT_SCHEDULE` and a `send_expiry_digests`
      management command. Links honour `LABBUTLER_BASE_URL`. 10 new tests (builders,
      recipients, outbox sends, on-commit hook); 87 total green, ruff clean.

## Notes / open spec items (defer until relevant)
- Shipping cost inside tax base? (assume yes)
- Multi-currency reporting: per-currency vs converted.
- Exact split of `approve_request` / `place_order` / order-responsible assignment.
