#!/usr/bin/env bash
# Proves a service's database schema can be built from its migrations alone
# (NFR-REC-001) and that every migration can be reversed: upgrade to head on an
# empty PostgreSQL + TimescaleDB, downgrade to base, then upgrade again.
#   usage: migration-check.sh <service>
#
# Service contract: services/<service>/alembic.ini exists and its env.py reads the
# connection string from DATABASE_URL (postgresql+asyncpg://...).
source "$(dirname "$0")/lib.sh"

service="${1:?usage: migration-check.sh <service>}"
if [[ ! -f "$REPO_ROOT/services/$service/alembic.ini" ]]; then
  log "services/$service has no alembic.ini, skipping"
  exit 0
fi

id="$(test_id)-$service"
network="$id"
db="$id-db"

cleanup() {
  docker rm -fv "$db" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$network" >/dev/null
docker run -d --name "$db" --network "$network" \
  -e POSTGRES_USER=qs -e POSTGRES_PASSWORD=qs -e POSTGRES_DB=qs \
  "$TIMESCALE_IMAGE" >/dev/null

# The image runs a temporary socket-only server during initialisation; a TCP check
# only succeeds once the real server is up.
log "waiting for the test database"
retry 60 2 docker exec "$db" pg_isready -h 127.0.0.1 -U qs -d qs >/dev/null \
  || die "test database did not start"

# The command runs inside the container, so its variables must not expand here
# shellcheck disable=SC2016
run_in_image "$UV_IMAGE" --network "$network" -e UV_LINK_MODE=copy -e SERVICE="$service" \
  -e "DATABASE_URL=postgresql+asyncpg://qs:qs@$db:5432/qs" -- bash -ec '
  export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.ci/uv-cache}"
  export UV_PROJECT_ENVIRONMENT="$PWD/.ci/venv-$SERVICE"
  cd "services/$SERVICE"
  uv sync --frozen
  echo "--- upgrade to head";   uv run --frozen alembic upgrade head
  echo "--- downgrade to base"; uv run --frozen alembic downgrade base
  echo "--- upgrade again";     uv run --frozen alembic upgrade head
'

log "migrations for $service apply cleanly from an empty database and reverse fully"
