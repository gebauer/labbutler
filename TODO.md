# LabButler — TODO

Living work list. Keep this current: check items off as they land, add notes when
decisions are made. Each major step ends in a commit (no push unless asked).

Spec & project context: [Buildspec.md](Buildspec.md) · Stack: Django 5 / Postgres 17 /
Celery+Redis / HTMX / Tailwind / uv.

## Decisions / conventions
- `sample_data/` is git-ignored (contains real PII). Used as a local import fixture only.
- Commit after every major step; never push unless asked.
- Multi-lab from the start, collapsible to one `Lab`.

## Done

- [x] **MVP build (steps 0–9)** — repo scaffold, tooling, data models, LabSuit importer
      (+ generic mapper wizard), inventory UI, procurement workflow UI, notifications.
      Detail lives in git history (`b718e9c` … `b5cdc9c`).
- [x] **Post-MVP (shipped through v1.0.0rc4)** — role-aware dashboard · lab admin
      (members/roles/suppliers/budgets/addresses/fields/settings) · location CRUD ·
      editable custom fields + audit panels · attachments & comment threads · receive
      dialog (check-in vs untracked) · forward-to-coordinator + `accept_forwards` ·
      self-approval · reorder from request/item · notification preferences + welcome /
      password-reset emails · LabSuit *orders* import with historical timestamps ·
      GHS catalog seeding + live lookup · item/request form reworks · teal design system,
      faceted filters, infinite scroll, table/cards toggle · security hardening
      (django-axes, CSP, HSTS, open-redirect fix) · version footer · Coolify deployment ·
      MkDocs docs site · privacy notice.
- [x] **Shipped through v1.1.0rc4** — mobile Data Matrix scanner with scan log ·
      Avery label-sheet printing · GHS lookup by CAS (PubChem) + pictograms on item
      detail · vendor normalisation, duplicate detection & merge UI · first-login
      onboarding tour · central-purchasing (Zentraleinkauf) route with PO workflow ·
      weekly per-member expiry reports · product-URL prefill · sortable request list.

## Rollout 1.0 — first lab deployment

From the pre-rollout audit of 2026-11-18 (`main` @ `f3ed0e1`, v1.1.0rc4: 529 tests
green, ruff clean, no missing migrations, `check --deploy` clean). Work top-down;
each fix is its own commit with tests.

### P1 — blockers (before go-live)
- [ ] **Upgrade Django 5.1 → 5.2 LTS.** 5.1 is out of security support since Dec 2025;
      pin is `django>=5.0,<5.2` in `pyproject.toml`. Run `--runslow` after.
- [ ] **Add `LOGGING` config.** With `DEBUG=False` and no `ADMINS`, 500 tracebacks are
      dropped silently. Log to console (→ `docker logs`), `django.request` at ERROR.
- [ ] **Pass all settings through `docker-compose.yml`.** Read by settings but never
      reach the containers: `EXPIRY_DIGEST_WEEKDAY`, `PASSWORD_RESET_TIMEOUT_DAYS`,
      `LABBUTLER_CENTRAL_PURCHASING_THRESHOLD_NET`, `LABBUTLER_PO_DEVIATION_THRESHOLD_PCT`,
      `LABBUTLER_EU_COUNTRIES`, `AXES_ENABLED`, `DJANGO_SECURE_HSTS_SECONDS`,
      `DJANGO_CONTENT_SECURITY_POLICY` (+ `HTTPS_PROXY` if the uni network needs one).
      Drop the dead `EXPIRY_DIGEST_DAYS`.
- [ ] **Verify the real LabSuit import.** The 4 real-export tests skip without
      `sample_data/`; run `uv run pytest --runslow` with the export in place, then a
      dry-run import on a DB copy.
- [ ] **Update the privacy notice.** Add the product-URL prefill (server fetches from
      Sigma, Roth, Fisher, Cytiva, Amazon); mention successful-login records; add the
      controller contact for this installation.
- [ ] **Retention for login records.** django-axes keeps `AccessLog` (IP + user agent of
      every login) and `AccessAttempt` forever — schedule a cleanup (e.g. 90 days).

### P2 — should fix soon after
- [ ] **Retry email tasks.** No Celery task retries; a transient SMTP failure silently
      drops mail, including the ZK forward email with the signed PO. Add
      `autoretry_for` SMTP/OS errors with backoff.
- [ ] **Lock requests during transitions.** `perform_transition` / `receive` check the
      status on the view's stale object — double submits send duplicate emails or 500 on
      check-in. Re-fetch with `select_for_update()`; add a global double-submit guard
      in `app.js`.
- [ ] **Clean up on item delete.** Attachments (rows + files) and comments are orphaned
      (no `GenericRelation`) — storage leak and GDPR issue.
- [ ] **Never leave a lab without a manager.** Block removing `manage_lab` from the last
      holder via member edit, role edit, and role delete.
- [ ] **Fail loudly without `LABBUTLER_BASE_URL`.** Blank → invitation emails carry a
      relative, unusable link. Add a system check when `DEBUG=False`.

### P3 — minor
- [ ] Comment links: reject `/\host` (browsers read it as `//host`) in
      `comment_links.py`.
- [ ] Product lookup: don't follow redirects off the vendor allowlist.
- [ ] Branded `403.html` / `404.html` / `500.html`.
- [ ] Vendors/budgets in use: archive instead of delete (delete nulls history).
- [ ] Pin the `uv` image in the `Dockerfile` (currently `:latest`).
- [ ] Docs: Buildspec §15 still lists shipped features as roadmap; README says the expiry
      digest is daily (it is weekly).
- [ ] Run a dependency CVE audit (`uvx pip-audit`) against `uv.lock`.

### Deployment checklist (ops, no code)
- [ ] Automated `pg_dump` + media-volume backup; **test a restore**.
- [ ] Strong `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` (default is `labbutler`).
- [ ] `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `LABBUTLER_BASE_URL` set.
- [ ] Uni SMTP relay + accepted `DEFAULT_FROM_EMAIL`; send a test email.
- [ ] Outbound HTTPS from the server (PubChem, vendor lookups) — proxy if required.
- [ ] Build with `GIT_COMMIT=$(git rev-parse --short HEAD) docker compose build`.
- [ ] Bump version, `--runslow` green, tag + GitHub release.

## Feature — onboarding & join requests

### Join link (self-service membership requests)
Today only a manager can add members (types the email, picks roles, welcome email goes
out). Goal: a shareable link people use to *ask* to join; the manager approves and
picks the role(s).

- [ ] **Model `JoinRequest`** (tenancy): lab, email, name, optional message, status
      (pending / approved / rejected), decided_by, decided_at, created_at. Unique
      pending request per (lab, lower(email)).
- [ ] **Join link per lab**: random token on `Lab` (or a `JoinLink` model), manager can
      enable/disable and **regenerate** it (revokes old link). Optional expiry.
- [ ] **Public request page** `/join/<token>/`: name, email, message → creates a pending
      request. No account is created and no existence leak ("request received" either
      way). Rate-limit + honeypot; CSRF as usual.
- [ ] **Email confirmation** of the requester's address before managers see it (stops
      spam / typo'd addresses).
- [ ] **Manager review**: "Join requests" tab under Manage → Members with a badge count;
      approve with role checkboxes (pre-select the lab's default role) or reject.
      Dashboard widget for pending requests; notify managers by email.
- [ ] **Approve = existing invite path**: reuse `add_member` + `send_welcome_email`, so
      the user sets a password via the welcome link. Existing users just gain the
      membership. Rejection sends a short neutral email.
- [ ] **Audit** every request/approve/reject; new permission (or reuse `manage_lab`).
- [ ] Tests: token validity/regeneration, duplicate requests, existing user, permission
      gating, no account enumeration. Docs in the user + admin guides.

### Better onboarding
Builds on the existing first-login tour (`/welcome/`, `onboarding_seen_at`).

- [ ] **Role-aware tour**: steps adapt to the roles granted (requester vs. orderer vs.
      manager vs. signer), so nobody reads about buttons they don't have.
- [ ] **Setup checklist on the dashboard** for new members (set display name, tune
      notifications, find your first item, raise a test request) — dismissible, ticks
      itself off.
- [ ] **Manager first-run checklist**: locations, suppliers, budgets, shipping
      addresses, roles, join link, import LabSuit data.
- [ ] **Welcome email polish**: who invited you, your roles, the lab name, link to the
      tour; German/English wording check.
- [ ] Empty states with next-step hints on inventory/requests for a brand-new lab.

## Later / roadmap

Roadmap detail lives in [Buildspec.md §15](Buildspec.md); still open:

- [ ] Low-stock alerts · batch container generation · tag merge tool (vendor merge shipped).
- [ ] Cross-lab sharing (`SharingGrant` + `cross_lab_search`) · institute tier.
- [ ] SSO/LDAP · scheduled backup/export · invoice reconciliation field.
      *SSO assessed 2026-07: Keycloak (AG Baumann realm) via `mozilla-django-oidc`,
      hybrid with password login, invite-first (no auto-create), ~150-line diff,
      ~1–1.5 days incl. tests/docs. Deferred — complexity vs. benefit. Plan:
      `~/.claude/plans/i-have-a-keycloak-transient-unicorn.md`.*
- [ ] Import gaps: CSV input for the generic mapper; optional serial dedup on generic
      imports; seed German GHS texts (`text_de`).
- [ ] Central purchasing v2 (see `Procurement.MD` §13): PDF token stamping, signature
      validation, vendored PDF.js preview, official-form prefill, post-approval editing.

### Open spec items (defer until relevant)
- Shipping cost inside tax base? (assume yes)
- Multi-currency reporting: per-currency vs converted.
