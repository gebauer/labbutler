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

## Next / open

Roadmap detail lives in [Buildspec.md §15](Buildspec.md) — single source; headline items:

- [ ] Mobile Data Matrix scanner (lookup / check-in / check-out by scanning the label).
- [ ] Label-sheet generator (printable HERMA-style template for reserved ID ranges).
- [ ] Auto H-P lookup by CAS (PubChem / ECHA) · vendor & tag merge tools.
- [ ] Low-stock alerts · batch container generation.
- [ ] Cross-lab sharing (`SharingGrant` + `cross_lab_search`) · institute tier.
- [ ] SSO/LDAP · scheduled backup/export · invoice reconciliation field.
      *SSO assessed 2026-07: Keycloak (AG Baumann realm) via `mozilla-django-oidc`,
      hybrid with password login, invite-first (no auto-create), ~150-line diff,
      ~1–1.5 days incl. tests/docs. Deferred — complexity vs. benefit. Plan:
      `~/.claude/plans/i-have-a-keycloak-transient-unicorn.md`.*
- [ ] Import gaps: CSV input for the generic mapper; optional serial dedup on generic
      imports; seed German GHS texts (`text_de`).

### Open spec items (defer until relevant)
- Shipping cost inside tax base? (assume yes)
- Multi-currency reporting: per-currency vs converted.
