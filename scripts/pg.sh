#!/usr/bin/env bash
# Project-local PostgreSQL helper.
#
# Runs a dedicated Postgres cluster under .pgdata/ on a non-default port so it never
# clashes with a system Postgres. Data lives inside the repo (git-ignored).
#
#   scripts/pg.sh init     # one-time: create the cluster + role + database
#   scripts/pg.sh start     # start the server
#   scripts/pg.sh stop      # stop the server
#   scripts/pg.sh status    # show server status
#   scripts/pg.sh psql      # open a psql shell on the project database
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGDATA="${ROOT_DIR}/.pgdata"
PGPORT="${LABBUTLER_PGPORT:-55432}"
PGUSER="labbutler"
PGDATABASE="labbutler"
export PGPORT

log() { printf '\033[1;34m[pg]\033[0m %s\n' "$*"; }

case "${1:-}" in
  init)
    if [[ -d "$PGDATA" ]]; then
      log "cluster already exists at $PGDATA"; exit 0
    fi
    log "initialising cluster at $PGDATA (port $PGPORT)"
    initdb -D "$PGDATA" -U "$PGUSER" --auth=trust >/dev/null
    pg_ctl -D "$PGDATA" -o "-p $PGPORT" -l "$PGDATA/server.log" start
    until pg_isready -p "$PGPORT" -q; do sleep 0.3; done
    createdb -p "$PGPORT" -U "$PGUSER" "$PGDATABASE"
    log "created database '$PGDATABASE' owned by '$PGUSER'"
    log "DATABASE_URL=postgres://${PGUSER}@localhost:${PGPORT}/${PGDATABASE}"
    ;;
  start)
    pg_ctl -D "$PGDATA" -o "-p $PGPORT" -l "$PGDATA/server.log" start
    ;;
  stop)
    pg_ctl -D "$PGDATA" stop
    ;;
  status)
    pg_ctl -D "$PGDATA" status
    ;;
  psql)
    psql -p "$PGPORT" -U "$PGUSER" "$PGDATABASE"
    ;;
  *)
    echo "usage: scripts/pg.sh {init|start|stop|status|psql}" >&2
    exit 2
    ;;
esac
