# Developer guide overview

This section is for contributors. LabButler is a deliberately boring, readable
stack:

| Layer | Choice |
|---|---|
| Backend | Django 5 (Python 3.11) |
| Database | PostgreSQL 17 (JSONB custom fields, GIN-indexed) |
| Async / scheduled | Celery + Redis |
| Frontend | Server-rendered Django templates + HTMX, Tailwind CSS |
| Packaging | uv (`pyproject.toml` + `uv.lock`) |
| Tests / lint | pytest + ruff |
| Deployment | Docker Compose |

There is no SPA, no REST API, no JavaScript build beyond Tailwind: views render
templates, HTMX swaps fragments for the interactive parts (live search, inline
actions), and everything else is plain forms.

- [Development setup](setup.md) — get it running locally in ten minutes.
- [Architecture](architecture.md) — the apps, the scoping/permission model, and
  the load-bearing design decisions.
- [Testing](testing.md) — how the test suite is organised and run.
- [Conventions & contributing](conventions.md) — style, commits, and the ground
  rules from `CLAUDE.md`.

The original design rationale and data model live in
[`Buildv1.MD`](https://github.com/gebauer/labbutler/blob/main/Buildv1.MD) at the
repository root.
