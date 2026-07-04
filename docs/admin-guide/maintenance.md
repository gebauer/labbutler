# Operation & maintenance

## What state exists

Only two things hold state; everything else is disposable:

- **PostgreSQL** (`pgdata` volume) — all application data.
- **Media volume** — uploaded attachments (SDS/MSDS, quotes, manuals).

## Backups

Back up both volumes. For the database, a plain dump is the simplest reliable
approach:

```bash
docker compose exec db pg_dump -U labbutler labbutler | gzip > labbutler-$(date +%F).sql.gz
```

Restore with `gunzip -c dump.sql.gz | docker compose exec -T db psql -U labbutler labbutler`
into a fresh database. Copy the media volume with your regular file backup.
Automate the dump (cron on the host) and test a restore before you need one.

## Upgrades

```bash
git pull
docker compose up -d --build
```

The web service applies database migrations on start; migrations are append-only
and reversible. Take a database backup before upgrading.

## Health & monitoring

- `GET /healthz` returns `200 ok` when the app can reach the database — wire it
  into your uptime monitoring. It is exempt from the HTTPS redirect so the
  container health check can call it over plain HTTP.
- Celery **worker** handles emails; **beat** triggers the daily digests. If
  notification mail stops arriving, check these two containers first
  (`docker compose logs worker beat`).

## Login lockouts

django-axes locks an IP + username after repeated failed sign-ins (HTTP 429 with a
lockout page). Locks clear automatically after the cool-off period, or reset all
of them early with:

```bash
docker compose run --rm web python manage.py axes_reset
```

## Management commands

Run any of these via `docker compose run --rm web python manage.py <command>`:

| Command | Purpose |
|---|---|
| `bootstrap_lab` | Guided first run: superuser + initial lab + template roles. |
| `import_labsuit <file>` | Import a LabSuit inventory export from the command line (same engine as the web wizard). |
| `import_labsuit_orders <file>` | Import LabSuit order history as procurement requests, keeping historical workflow dates. |
| `backfill_order_timestamps` | Align created/updated timestamps of imported requests with their historical dates. |
| `send_expiry_digests` | Send the expiry digest immediately (normally done daily by beat). |
| `axes_reset` | Clear all login lockouts. |

## The Django admin

`/admin/` is the raw Django admin, available to superusers only. It bypasses the
lab-scoped permission system, so treat it as a break-glass tool for data surgery,
not a daily interface — normal administration happens in the app under **Manage**.
