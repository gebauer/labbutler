# Installation

Production runs entirely via **Docker Compose**. (For running from source without
Docker — the development setup — see the
[developer guide](../dev-guide/setup.md).)

## Docker Compose

### 1. Configure

```bash
git clone https://github.com/gebauer/labbutler.git
cd labbutler
cp .env.example .env
```

Edit `.env`. The minimum you must set:

- `DJANGO_SECRET_KEY` — a long random string:
  `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`
- `DJANGO_DEBUG=false`
- `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` — your domain
- `POSTGRES_PASSWORD` — a strong, URL-safe password (the app's `DATABASE_URL` is
  derived from the `POSTGRES_*` variables automatically, so app and DB can never
  drift apart)
- `EMAIL_*` and `DEFAULT_FROM_EMAIL` — your SMTP relay
- `LABBUTLER_BASE_URL` — the public URL, used for links in emails (required for
  the set-password links in welcome emails to work)

The full list is in the [configuration reference](configuration.md).

### 2. Start

```bash
docker compose up -d --build
```

- The **web** service runs database migrations on start.
- Static assets (Tailwind CSS, vendored htmx/Sortable) are built and collected at
  image build time and served by WhiteNoise — no separate static step, no CDN.
- Health probe: `GET /healthz` returns `200 ok` when the database is reachable;
  the web container's health check uses it.

### 3. First run: create the superuser and the lab

```bash
docker compose run --rm web python manage.py bootstrap_lab
```

`bootstrap_lab` is a guided first-run: it creates the **superuser**, the initial
**lab** (name, item-ID prefix), and clones the template roles into it. Afterwards,
sign in and add your members under **Manage → Members**.

### 4. Put a reverse proxy in front

Terminate TLS in a reverse proxy (nginx, Caddy, Traefik) and forward
`X-Forwarded-Proto` (and `X-Forwarded-For`). The app then enforces HTTPS redirect,
HSTS, and secure cookies — tunable via the `DJANGO_SECURE_*` variables.

!!! important "Set the proxy count"
    Login brute-force protection locks out by **client IP** + username. Behind a
    proxy you must set `AXES_IPWARE_PROXY_COUNT` to the number of proxy hops
    (usually `1`), otherwise every visitor appears to share the proxy's IP and one
    person's failed logins can lock out everyone.

## Deploying on Coolify

LabButler drops into [Coolify](https://coolify.io) cleanly — Coolify's Traefik
terminates TLS and forwards the headers the app already trusts.

1. **New Resource → Docker Compose**, pointed at this repository (it picks up
   `docker-compose.yml` with `web`, `db`, `broker`, `worker`, `beat`). Assign your
   domain to the **web** service.
2. Set the environment variables in Coolify (injected into the compose):

    | Variable | Value |
    |---|---|
    | `DJANGO_SECRET_KEY` | long random string |
    | `DJANGO_DEBUG` | `false` |
    | `DJANGO_ALLOWED_HOSTS` | `labbutler.your.domain` |
    | `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://labbutler.your.domain` |
    | `LABBUTLER_BASE_URL` | `https://labbutler.your.domain` |
    | `POSTGRES_PASSWORD` | a strong password |
    | `AXES_IPWARE_PROXY_COUNT` | `1` (Coolify's proxy is the one hop) |
    | `EMAIL_*`, `DEFAULT_FROM_EMAIL` | your SMTP details |

3. **Deploy.** `web` migrates on start; static assets are already in the image.
4. **First run only:** open the web container's terminal in Coolify and run
   `python manage.py bootstrap_lab`.
5. Coolify persists the `pgdata` and `media` volumes across redeploys —
   **[back up `pgdata`](maintenance.md#backups)**.

!!! tip "Troubleshooting on Coolify"
    - **HTTPS redirect loop** → set `DJANGO_SECURE_SSL_REDIRECT=false` (Coolify
      already redirects http→https at the edge).
    - To use Coolify's **managed** Postgres/Redis instead of the bundled ones,
      point `DATABASE_URL` / `CELERY_BROKER_URL` at them and drop the `db` /
      `broker` services.
