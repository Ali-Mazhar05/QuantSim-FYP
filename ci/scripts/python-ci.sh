#!/usr/bin/env bash
# Lints, type checks and tests one Python project in a pinned uv + Python container.
#   usage: python-ci.sh <project>
#     <project> is a folder such as services/market or libs/qs_template; a bare name
#     means services/<name>
#
# Project contract (<project>/pyproject.toml):
#   - dependencies locked in the workspace uv.lock at the repository root
#   - ruff, mypy and pytest in the dev dependency group
#   - at least one test; a project with no tests fails CI
# Tests marked @pytest.mark.db or @pytest.mark.kafka get a throwaway database or broker
# (see below). Results land in <project>/reports/junit.xml.
source "$(dirname "$0")/lib.sh"

project="${1:?usage: python-ci.sh <project>}"
[[ "$project" == */* ]] || project="services/$project"
[[ -f "$REPO_ROOT/$project/pyproject.toml" ]] || die "$project has no pyproject.toml"
name="$(basename "$project")"

# Throwaway services for tests that need them, on a network of their own:
#   @pytest.mark.db     PostgreSQL + TimescaleDB  -> TEST_DATABASE_URL
#   @pytest.mark.kafka  Redpanda                  -> TEST_KAFKA_BOOTSTRAP
uses() { grep -rqE "mark\.$1\b" "$REPO_ROOT/$project/tests" 2>/dev/null; }
service_opts=()
if uses db || uses kafka; then
  id="$(test_id)-$name"
  network="$id"
  cleanup() {
    docker rm -fv "$id-db" "$id-kafka" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
  }
  trap cleanup EXIT
  # Stops waiting as soon as the broker has exited, and shows why
  broker_ready() {
    if [[ "$(docker inspect -f '{{.State.Running}}' "$id-kafka" 2>/dev/null)" != "true" ]]; then
      # The reason is near the top; a usage message may follow it
      docker logs "$id-kafka" 2>&1 | head -n 15 >&2 || true
      die "test broker exited while starting (its log is above)"
    fi
    docker exec "$id-kafka" rpk cluster health --exit-when-healthy >/dev/null 2>&1
  }
  docker network create "$network" >/dev/null
  service_opts=(--network "$network")

  if uses db; then
    docker run -d --name "$id-db" --network "$network" \
      -e POSTGRES_USER=qs -e POSTGRES_PASSWORD=qs -e POSTGRES_DB=qs \
      "$TIMESCALE_IMAGE" >/dev/null
  fi
  if uses kafka; then
    docker run -d --name "$id-kafka" --network "$network" "$REDPANDA_IMAGE" \
      redpanda start --mode dev-container --smp 1 --memory 512M --overprovisioned \
      --kafka-addr "internal://0.0.0.0:9092" \
      --advertise-kafka-addr "internal://$id-kafka:9092" >/dev/null
  fi
  if uses db; then
    # The image runs a temporary socket-only server during initialisation; a TCP check
    # only succeeds once the real server is up.
    log "waiting for the test database"
    retry 60 2 docker exec "$id-db" pg_isready -h 127.0.0.1 -U qs -d qs >/dev/null \
      || die "test database did not start"
    service_opts+=(-e "TEST_DATABASE_URL=postgresql+asyncpg://qs:qs@$id-db:5432/qs")
  fi
  if uses kafka; then
    log "waiting for the test broker"
    retry 60 2 broker_ready || die "test broker did not start"
    service_opts+=(-e "TEST_KAFKA_BOOTSTRAP=$id-kafka:9092")
  fi
fi

# Each project gets its own virtualenv so projects can be checked in parallel.
# The command runs inside the container, so its variables must not expand here.
# shellcheck disable=SC2016
run_in_image "$UV_IMAGE" "${service_opts[@]}" -e UV_LINK_MODE=copy -e PROJECT="$project" -e NAME="$name" -- bash -ec '
  export UV_CACHE_DIR="$PWD/.ci/uv-cache"
  export UV_PROJECT_ENVIRONMENT="$PWD/.ci/venv-$NAME"
  cd "$PROJECT"
  uv sync --frozen
  echo "--- ruff";   uv run --frozen ruff check .
  echo "--- format"; uv run --frozen ruff format --check .
  echo "--- mypy";   uv run --frozen mypy .
  echo "--- pytest"; uv run --frozen pytest --junitxml=reports/junit.xml
'
