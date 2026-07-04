# Configuration reference

All configuration is via **environment variables** — in production through `.env`
next to `docker-compose.yml` (start from `.env.example`), never through files in
the image. There are no secrets in the repository.

## Django core

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | — (required) | Django's signing key. Long and random; rotating it invalidates sessions and unexpired password-reset links. |
| `DJANGO_DEBUG` | `false` | Never `true` in production. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hostnames the app may serve. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | (empty) | Comma-separated origins incl. scheme, e.g. `https://labbutler.your.domain`. |
| `DJANGO_TIME_ZONE` | `Europe/Berlin` | Display/default time zone. |
| `DJANGO_MEDIA_ROOT` | `/data/media` | Where uploaded attachments are stored (the compose media volume). |

## Database

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `labbutler` | Credentials for the bundled `db` service. `DATABASE_URL` is **derived from these automatically**, so app and database can never disagree. Use a URL-safe password. |
| `DATABASE_URL` | (derived) | Set only to override — e.g. a managed/external PostgreSQL. URL-encode special characters. PostgreSQL is required; SQLite is not supported. |

## Celery / Redis

| Variable | Default | Purpose |
|---|---|---|
| `CELERY_BROKER_URL` | `redis://broker:6379/0` | Message broker. |
| `CELERY_RESULT_BACKEND` | `redis://broker:6379/1` | Result store. |
| `CELERY_TASK_ALWAYS_EAGER` | `false` | Run tasks inline (dev/test only). |

## Email

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_EMAIL_BACKEND` | SMTP backend | Swap for the console backend in dev. |
| `EMAIL_HOST` / `EMAIL_PORT` | `localhost` / `25` | SMTP relay. |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | (empty) | SMTP credentials. |
| `EMAIL_USE_TLS` | `false` | STARTTLS. |
| `DEFAULT_FROM_EMAIL` | — | Sender address for all outgoing mail. |
| `PASSWORD_RESET_TIMEOUT_DAYS` | `3` | Days a password-reset / invite set-password link stays valid. |

## Notifications

| Variable | Default | Purpose |
|---|---|---|
| `LABBUTLER_BASE_URL` | (empty) | Absolute public URL used for links in emails. Leave blank to omit links — but then set-password links in welcome emails won't work. |
| `EXPIRY_DIGEST_DAYS` | `30` | Look-ahead window for the expiry digest. |
| `EXPIRY_DIGEST_HOUR` | `7` | Local hour the daily expiry digest is sent. |
| `NOTIFY_DIGEST_HOUR` | `7` | Local hour the daily procurement digest is sent (at :30). |

## Login brute-force protection (django-axes)

| Variable | Default | Purpose |
|---|---|---|
| `AXES_ENABLED` | `true` | Master switch. |
| `AXES_FAILURE_LIMIT` | `5` | Failed sign-ins (per IP + username) before lockout. Lockouts answer HTTP 429 and reset on a successful login. |
| `AXES_COOLOFF_HOURS` | `1` | Hours before an automatic unlock. |
| `AXES_IPWARE_PROXY_COUNT` | `0` | **Number of reverse proxies in front.** With `0` behind a proxy, all users share the proxy's IP — set it (usually `1`). |

## HTTPS hardening

Active whenever `DJANGO_DEBUG=false`; the app expects `X-Forwarded-Proto` from
your proxy. `GET /healthz` is exempt from the redirect so container health checks
can use plain HTTP.

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECURE_SSL_REDIRECT` | `true` | Redirect http→https in the app. Set `false` if the proxy already does it (e.g. Coolify) and you hit a redirect loop. |
| `DJANGO_SECURE_HSTS_SECONDS` | `31536000` | HSTS max-age (1 year), incl. subdomains + preload. |

Secure session/CSRF cookies are always on outside debug.

## Impersonation

| Variable | Default | Purpose |
|---|---|---|
| `LABBUTLER_IMPERSONATION_ENABLED` | `false` in production | Superuser "view as another user" for testing role setups. Every action while impersonating is audit-logged with the real superuser. Enable deliberately, or leave off. |
