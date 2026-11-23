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
#
# The suites sign in as QS_E2E_USERNAME with QS_E2E_PASSWORD. When they are not set the
# gate uses test.admin, which the platform's seed-test-users creates on every DEV and TEST
# deploy with TEST_USERS_PASSWORD from deploy/secrets/<env>.enc.env; the password is
# decrypted here like deploy.sh does (needs SOPS_AGE_KEY_FILE) and never printed.
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

export QS_E2E_USERNAME="${QS_E2E_USERNAME:-test.admin}"
if [[ -z "${QS_E2E_PASSWORD:-}" ]]; then
  read_secret "$env" TEST_USERS_PASSWORD QS_E2E_PASSWORD
fi

# The API is reached through a Cloudflare quick tunnel, whose name resolves to two Cloudflare
# addresses. When this network cannot reach one of them (22 Nov: 104.16.230.132 did not
# answer at all), a browser that tries it first waits ~10 s per connection, and the suites
# time out at sign-in. The address that works is found here and the browser told to use
# it; when every address answers, nothing changes. The log says which address was dropped.
api_host="$(curl -fsS -m 20 "$base_url/config.json" 2>/dev/null \
  | sed -n 's#.*"apiBaseUrl" *: *"https\{0,1\}://\([^/"]*\).*#\1#p')"
export QS_E2E_HOST_RULES=""
if [[ -n "$api_host" ]]; then
  mapfile -t addresses < <(getent ahostsv4 "$api_host" | awk '{print $1}' | sort -u)
  reachable=() unreachable=()
  for address in "${addresses[@]}"; do
    if curl -fsS -o /dev/null -m 5 --resolve "$api_host:443:$address" "https://$api_host/api/platform/health"; then
      reachable+=("$address")
    else
      unreachable+=("$address")
    fi
  done
  if (( ${#unreachable[@]} && ${#reachable[@]} )); then
    QS_E2E_HOST_RULES="MAP $api_host ${reachable[0]}"
    log "WARNING: this network cannot reach $api_host at ${unreachable[*]}; the browser uses ${reachable[0]} (people on this network see slow first requests to the API)"
  elif (( ${#unreachable[@]} )); then
    log "WARNING: $api_host answers on none of ${unreachable[*]}"
  fi
fi

log "running Playwright suite $suite against $base_url as $QS_E2E_USERNAME"
# The command runs inside the container, so its variables must not expand here. The
# account is passed by name only (-e NAME), so its password never appears in a command line.
# shellcheck disable=SC2016
run_in_image "$PLAYWRIGHT_IMAGE" -e CI=true -e PLAYWRIGHT_BASE_URL="$base_url" \
  -e QS_E2E_SUITE="$suite" -e PLAYWRIGHT_JUNIT_OUTPUT_NAME="reports/e2e-$suite.xml" \
  -e QS_E2E_USERNAME -e QS_E2E_PASSWORD -e QS_E2E_HOST_RULES -- sh -ec '
  cd frontend
  npm ci --no-audit --no-fund
  npx playwright test "e2e/$QS_E2E_SUITE" --reporter=line,junit
'
log "Playwright suite $suite passed"
