# Development setup

Dev runs natively (no Docker) for a fast inner loop.

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **PostgreSQL 17** server binaries — the repo runs a *project-local* instance on
  port 55432 so it never clashes with a system Postgres
- **Redis** — `sudo apt install redis-server && sudo service redis-server start`
- **Node + npm** — only for building Tailwind CSS

## First-time setup

```bash
git clone https://github.com/gebauer/labbutler.git
cd labbutler

# Python deps into a project-local .venv
uv sync

# Environment
cp .env.example .env
# For dev, point DATABASE_URL at the project-local Postgres:
#   DATABASE_URL=postgres://labbutler@localhost:55432/labbutler

# Project-local Postgres (data dir inside the repo, port 55432)
scripts/pg.sh init      # once
scripts/pg.sh start     # each session; pg.sh stop when done

# Schema + first admin & lab
uv run manage.py migrate
uv run manage.py bootstrap_lab

# Tailwind
npm install
```

## Daily loop

```bash
scripts/pg.sh start                            # if not already running
uv run manage.py runserver                     # app on http://localhost:8000
npm run dev                                    # tailwind --watch, second terminal
uv run celery -A labbutler worker -l info      # only if you need emails/tasks
```

Most work doesn't need the Celery worker; set `CELERY_TASK_ALWAYS_EAGER=true` in
`.env` (or use the console email backend) to see task effects without one.

## Common commands

| Task | Command |
|---|---|
| Run tests | `uv run pytest` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Make migrations | `uv run manage.py makemigrations` |
| Django shell | `uv run manage.py shell` |
| Add a dependency | `uv add <package>` |
| Build docs locally | `uv run mkdocs serve` |
| Production CSS build | `npm run build` |

## Sample data

If you have a LabSuit export, import it for a realistic dataset:

```bash
uv run manage.py import_labsuit path/to/export.xlsx
```

(`sample_data/` is git-ignored — real exports contain PII and must never be
committed.)
