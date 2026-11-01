#!/usr/bin/env bash
# =============================================================================
# CodeSage — disposable test dependencies (PostgreSQL + Redis)
# =============================================================================
# Starts two throwaway containers bound to loopback only:
#
#   codesage-test-db      postgres:16-alpine  127.0.0.1:5432   codesage_test + codesage_e2e
#   codesage-test-redis   redis:7-alpine      127.0.0.1:6379   db 15 = pytest, db 14 = E2E
#
# The standard ports are used on purpose: backend/tests/conftest.py hard-codes
# `localhost:5432` and `redis://localhost:6379/15` (CI parity) and must not be
# modified. Nothing outside loopback can reach these containers.
#
# Usage:
#   scripts/testing/start-test-deps.sh            # start (idempotent)
#   scripts/testing/start-test-deps.sh --reset    # drop + recreate both databases
#   scripts/testing/start-test-deps.sh --down     # remove the containers
#   scripts/testing/start-test-deps.sh --status   # show status
# =============================================================================
set -euo pipefail

PG_CONTAINER="codesage-test-db"
REDIS_CONTAINER="codesage-test-redis"
PG_IMAGE="postgres:16-alpine"
REDIS_IMAGE="redis:7-alpine"
PG_USER="codesage"
PG_PASSWORD="codesage"
DB_PYTEST="codesage_test"
DB_E2E="codesage_e2e"

info() { printf '\033[36m[deps]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[deps]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[deps]\033[0m %s\n' "$*" >&2; }

require_docker() {
  command -v docker >/dev/null 2>&1 || { err "docker is not installed"; exit 1; }
  docker info >/dev/null 2>&1 || { err "the Docker daemon is not reachable"; exit 1; }
}

port_open() {  # port_open <port>
  (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1 && { exec 3>&- 3<&-; return 0; } || return 1
}

container_state() {  # container_state <name> -> running|exited|absent
  local state
  state="$(docker inspect -f '{{.State.Status}}' "$1" 2>/dev/null | tr -d '[:space:]' || true)"
  [[ -n "$state" ]] || state=absent
  printf '%s' "$state"
}

wait_for() {  # wait_for <description> <cmd...>
  local desc="$1"; shift
  for _ in $(seq 1 60); do
    if "$@" >/dev/null 2>&1; then ok "$desc ready"; return 0; fi
    sleep 1
  done
  err "timeout waiting for $desc"
  return 1
}

ensure_container() {  # ensure_container <name> <image> <run-args...>
  local name="$1" image="$2"; shift 2
  local state
  state="$(container_state "$name")"
  case "$state" in
    running) info "$name already running" ;;
    exited|created|paused)
      info "starting existing $name"
      docker start "$name" >/dev/null ;;
    absent)
      info "creating $name ($image)"
      docker run -d --name "$name" "$@" "$image" >/dev/null ;;
    *)
      err "unexpected container state for $name: $state"; exit 1 ;;
  esac
}

pg_up() {
  if [[ "$(container_state "$PG_CONTAINER")" == absent ]] && port_open 5432; then
    err "port 5432 is already in use by a non-CodeSage service."
    err "Stop it first (this stack must own localhost:5432 for CI parity)."
    exit 1
  fi
  ensure_container "$PG_CONTAINER" "$PG_IMAGE" \
    --label codesage.testing=true \
    --publish 127.0.0.1:5432:5432 \
    --env POSTGRES_USER="$PG_USER" \
    --env POSTGRES_PASSWORD="$PG_PASSWORD" \
    --env POSTGRES_DB="$DB_PYTEST" \
    --health-cmd "pg_isready -U $PG_USER" \
    --health-interval 2s --health-timeout 3s --health-retries 30

  wait_for "postgres" docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -q
  ensure_database "$DB_PYTEST"
  ensure_database "$DB_E2E"
}

ensure_database() {  # ensure_database <name>
  local db="$1" exists=""
  # The initdb entrypoint starts answering pg_isready before POSTGRES_DB is
  # committed, so poll until the catalog is actually queryable.
  for _ in $(seq 1 60); do
    exists="$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname='$db'" 2>/dev/null | tr -d '[:space:]' || true)"
    [[ -n "$exists" ]] && break
    sleep 1
  done
  if [[ "$exists" == "1" ]]; then
    info "database $db present"
    return 0
  fi
  info "creating database $db"
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -q -c "CREATE DATABASE $db" >/dev/null 2>&1 || true
  exists="$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='$db'" 2>/dev/null | tr -d '[:space:]' || true)"
  [[ "$exists" == "1" ]] || { err "could not create database $db"; exit 1; }
}

redis_up() {
  if [[ "$(container_state "$REDIS_CONTAINER")" == absent ]] && port_open 6379; then
    err "port 6379 is already in use by a non-CodeSage service."
    err "Stop it first (this stack must own localhost:6379 for CI parity)."
    exit 1
  fi
  ensure_container "$REDIS_CONTAINER" "$REDIS_IMAGE" \
    --label codesage.testing=true \
    --publish 127.0.0.1:6379:6379 \
    --health-cmd "redis-cli ping" \
    --health-interval 2s --health-timeout 3s --health-retries 30

  wait_for "redis" docker exec "$REDIS_CONTAINER" redis-cli ping
}

reset_databases() {
  info "resetting $DB_PYTEST and $DB_E2E"
  for db in "$DB_PYTEST" "$DB_E2E"; do
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -q \
      -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$db'" >/dev/null 2>&1 || true
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -q -c "DROP DATABASE IF EXISTS $db" >/dev/null
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -q -c "CREATE DATABASE $db" >/dev/null
  done
  docker exec "$REDIS_CONTAINER" redis-cli -n 14 flushdb >/dev/null
  docker exec "$REDIS_CONTAINER" redis-cli -n 15 flushdb >/dev/null
  ok "databases recreated, Redis db 14/15 flushed"
}

down() {
  for name in "$PG_CONTAINER" "$REDIS_CONTAINER"; do
    if [[ "$(container_state "$name")" != absent ]]; then
      local owner
      owner="$(docker inspect -f '{{ index .Config.Labels "codesage.testing" }}' "$name" 2>/dev/null || true)"
      [[ "$owner" == true ]] || { err "refusing to remove $name: it is not labeled codesage.testing=true"; exit 1; }
      info "removing $name"
      docker rm -f "$name" >/dev/null
    fi
  done
  ok "test dependencies removed"
}

status() {
  printf '%-22s %-10s %s\n' CONTAINER STATE PORTS
  for name in "$PG_CONTAINER" "$REDIS_CONTAINER"; do
    printf '%-22s %-10s %s\n' "$name" "$(container_state "$name")" \
      "$(docker inspect -f '{{range $p, $c := .NetworkSettings.Ports}}{{if $c}}{{$p}} {{end}}{{end}}' "$name" 2>/dev/null || echo -)"
  done
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -tAc \
    "SELECT datname FROM pg_database WHERE datname IN ('$DB_PYTEST','$DB_E2E') ORDER BY 1" 2>/dev/null \
    | sed 's/^/  database: /' || true
}

main() {
  require_docker
  case "${1:-up}" in
    up|--up)     pg_up; redis_up; ok "test dependencies ready (postgres 127.0.0.1:5432, redis 127.0.0.1:6379)" ;;
    --reset)     pg_up; redis_up; reset_databases ;;
    --down)      down ;;
    --status)    status ;;
    -h|--help)   sed -n '2,25p' "$0" ;;
    *)           err "unknown option: $1"; exit 2 ;;
  esac
}

main "$@"
