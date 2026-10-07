#!/usr/bin/env bash
# Lints, type checks and tests one backend service in a pinned uv + Python container.
#   usage: python-ci.sh <service>
#
# Service contract (services/<service>/pyproject.toml):
#   - dependencies locked with uv (its own uv.lock, or the workspace uv.lock at the root)
#   - ruff, mypy and pytest available in the dev dependency group
#   - at least one test; a service with no tests fails CI
# Test results land in services/<service>/reports/junit.xml.
source "$(dirname "$0")/lib.sh"

service="${1:?usage: python-ci.sh <service>}"
[[ -f "$REPO_ROOT/services/$service/pyproject.toml" ]] || die "services/$service has no pyproject.toml"

# Each service gets its own virtualenv so services can be checked in parallel
# The command runs inside the container, so its variables must not expand here
# shellcheck disable=SC2016
run_in_image "$UV_IMAGE" -e UV_LINK_MODE=copy -e SERVICE="$service" -- bash -ec '
  export UV_CACHE_DIR="$PWD/.ci/uv-cache"
  export UV_PROJECT_ENVIRONMENT="$PWD/.ci/venv-$SERVICE"
  cd "services/$SERVICE"
  uv sync --frozen
  echo "--- ruff";   uv run --frozen ruff check .
  echo "--- format"; uv run --frozen ruff format --check .
  echo "--- mypy";   uv run --frozen mypy .
  echo "--- pytest"; uv run --frozen pytest --junitxml=reports/junit.xml
'
