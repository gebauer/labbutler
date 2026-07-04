# Installation & operation overview

This section is for whoever runs the LabButler server. The short version:

- LabButler is a **12-factor Django application**: all configuration comes from
  environment variables, state lives in PostgreSQL and a media volume, and the
  production stack is one `docker compose up`.
- The stack is five services: **web** (Django/Gunicorn), **db** (PostgreSQL 17),
  **broker** (Redis), and **worker** + **beat** (Celery, for emails and daily
  digests).
- You put a **TLS-terminating reverse proxy** in front (or let
  [Coolify](installation.md#deploying-on-coolify) do it) and forward
  `X-Forwarded-Proto`.

| I want to… | Go to |
|---|---|
| Install it | [Installation](installation.md) — Docker Compose or Coolify |
| Look up an environment variable | [Configuration reference](configuration.md) |
| Back up, upgrade, run commands | [Operation & maintenance](maintenance.md) |
| Hack on the code | [Developer guide](../dev-guide/index.md) |

!!! info "Sizing"
    LabButler is built for a single research institute — a small VM (2 vCPU / 2 GB
    RAM) comfortably runs the whole stack for a lab of dozens of members and tens
    of thousands of items.
