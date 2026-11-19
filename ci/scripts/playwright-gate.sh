#!/usr/bin/env bash
# Runs a Playwright suite against an environment's deployed website. A red run fails the
# deploy, so the environment never gets its verified status and the next promotion pull
# request stays blocked.
#   usage: playwright-gate.sh <env> <suite>
#
#   dev  dev-smoke    sign-in and every page loads (A21); gates develop -> test
#   test demo-spine   the demo spine (Lane B); gates test -> acceptance
#
# The suite lives in frontend/e2e/<suite>/. Until it exists the gate is skipped with a
# notice, so the pipeline can carry the stage before the tests are written.
source "$(dirname "$0")/lib.sh"

env="${1:?usage: playwright-gate.sh <env> <suite>}"
suite="${2:?usage: playwright-gate.sh <env> <suite>}"

load_env "$env"

if [[ ! -d "$REPO_ROOT/frontend/e2e/$suite" ]]; then
  log "no Playwright suite at frontend/e2e/$suite yet; gate skipped"
  exit 0
fi

case "$FRONTEND_TARGET" in
  pages)   base_url="$(pages_url)" ;;
  compose) require_env SMOKE_BASE_URL; base_url="$SMOKE_BASE_URL" ;;
  *)       die "unknown FRONTEND_TARGET: $FRONTEND_TARGET" ;;
esac

log "running Playwright suite $suite against $base_url"
# The command runs inside the container, so its variables must not expand here
# shellcheck disable=SC2016
run_in_image "$PLAYWRIGHT_IMAGE" -e CI=true -e PLAYWRIGHT_BASE_URL="$base_url" \
  -e QS_E2E_SUITE="$suite" -e PLAYWRIGHT_JUNIT_OUTPUT_NAME="reports/e2e-$suite.xml" -- sh -ec '
  cd frontend
  npm ci --no-audit --no-fund
  npx playwright test "e2e/$QS_E2E_SUITE" --reporter=line,junit
'
log "Playwright suite $suite passed"
