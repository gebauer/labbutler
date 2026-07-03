---
name: dev-server
description: Start and smoke-test the LabButler Django dev server (project-local Postgres on port 55432, runserver on 8000). Use when asked to run/start/launch the app or verify a change in the browser.
---

# Run the LabButler dev server

## 1. Postgres (project-local cluster, port 55432)

The repo runs its own Postgres under `.pgdata/` on **port 55432** (not 5432), so it
never clashes with a system Postgres. Check before starting — `pg.sh start` errors
with "lock file postmaster.pid already exists" if it's already up, which is harmless
but looks like a failure:

```bash
scripts/pg.sh status || scripts/pg.sh start
```

First-time setup only (no `.pgdata/` yet): `scripts/pg.sh init`, then
`uv run python manage.py migrate`.

## 2. Apply migrations and start the server (background)

```bash
uv run python manage.py migrate        # no-op if current
uv run python manage.py runserver 0.0.0.0:8000   # run in background
```

Launch `runserver` as a background task; it serves at http://localhost:8000 and
reloads on code changes. Static files are served by Django in dev — no collectstatic
needed. Tailwind CSS is pre-built; only run `npm run dev` (watch) if you are editing
Tailwind classes and styles look stale.

Celery tasks (emails/notifications) are enqueued but not executed unless a worker
runs: `uv run celery -A labbutler worker -l info` (usually unnecessary for UI work).

## 3. Smoke-test (quote URLs — zsh globs `?`)

```bash
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8000/accounts/login/"   # expect 200
```

Most pages require login and an active lab membership; anonymous requests 302 to
`/accounts/login/`. To drive an authenticated flow without browser login, exercise
the code against the dev DB via `uv run python manage.py shell -c "..."`.

## 4. Stop

Kill the background runserver task; `scripts/pg.sh stop` only if the user wants
Postgres down too (it's cheap to leave running).
