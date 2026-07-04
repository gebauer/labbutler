# LabButler production image: Django + Gunicorn, with the Tailwind CSS prebuilt.
# Stage 1 — build the CSS bundle with Node.
FROM node:22-slim AS css
WORKDIR /build
COPY package.json package-lock.json* ./
RUN npm install
COPY tailwind.config.js ./
COPY labbutler/static/css/input.css ./labbutler/static/css/input.css
COPY templates ./templates
COPY apps ./apps
RUN npm run build

# Stage 2 — Python runtime.
FROM python:3.11-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local

# uv for fast, locked dependency installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cache-friendly), without the project itself.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Application code.
COPY . .
# Bring in the CSS built in stage 1.
COPY --from=css /build/labbutler/static/css/dist.css ./labbutler/static/css/dist.css

RUN uv sync --frozen --no-dev \
    && DJANGO_SECRET_KEY=build DATABASE_URL=postgres://u@localhost/db \
       python manage.py collectstatic --noinput

# Run unprivileged. /data/media is created here so the named volume inherits this
# ownership on first use and uploads stay writable.
RUN useradd --system --create-home labbutler \
    && mkdir -p /data/media \
    && chown -R labbutler:labbutler /data/media
USER labbutler

# Commit hash for the footer's build link; .git is not in the image, so it must
# be passed at build time (see docker-compose.yml / CI).
ARG GIT_COMMIT=""
ENV LABBUTLER_COMMIT=$GIT_COMMIT

EXPOSE 8000
CMD ["gunicorn", "labbutler.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
