#!/usr/bin/env bash
# Live check of the Trading API and engine on a deployed environment: through the gateway
# it creates a strategy and a portfolio on the demo market environment, runs the engine,
# and checks the run's whole hash-chained event log, the ops metrics, the A-NFR-01
# benchmark and, last, a load step (ci/scripts/trading_live_check.py lists every step).
# A failure fails the deploy, so the environment is not verified.
#   usage: trading-live-check.sh <env>
#
# Needs the demo environments, which only LOCAL and DEV may enable
# (TRADING_DEMO_ENVIRONMENTS in deploy/env/<env>.env). It signs in as test.admin, and
# checks a viewer rule as test.viewer; the platform's seed-test-users creates both on
# every DEV deploy with TEST_USERS_PASSWORD, which is decrypted here from
# deploy/secrets/<env>.enc.env (needs SOPS_AGE_KEY_FILE) unless QS_LIVE_PASSWORD is set,
# and passed on by name only, never printed.
source "$(dirname "$0")/lib.sh"

env="${1:?usage: trading-live-check.sh <env>}"
load_env "$env"
# Same override as smoke.sh, for hosts that cannot reach host.docker.internal
SMOKE_BASE_URL="${SMOKE_BASE_URL_OVERRIDE:-${SMOKE_BASE_URL:-}}"
require_env SMOKE_BASE_URL
[[ -n "${TRADING_DEMO_ENVIRONMENTS:-}" ]] \
  || die "$env has no demo market environment (TRADING_DEMO_ENVIRONMENTS); the live check runs on DEV only"

# The replay environment shipped in the trading image (services/trading/src/qs_trading/demo)
export QS_LIVE_ENV_ID="${QS_LIVE_ENV_ID:-5d0c6c1e-7a14-4a14-8a14-000000000001}"
export QS_LIVE_BASE_URL="$SMOKE_BASE_URL"
export QS_LIVE_USERNAME="${QS_LIVE_USERNAME:-test.admin}"
export QS_LIVE_VIEWER_USERNAME="${QS_LIVE_VIEWER_USERNAME-test.viewer}"
# A second quant (same seeded password), refused when editing another quant's strategy
export QS_LIVE_QUANT_USERNAME="${QS_LIVE_QUANT_USERNAME-test.quant}"
# A-NFR-01: the 40 x 252 benchmark environment in the trading image; empty skips it
# J2 over the DEV stand-in feed (TRADING_DEMO_FEEDS): the recorded 2020 replay over HTTP
# and its copy among the demo environments
if [[ "${TRADING_DEMO_FEEDS:-false}" == true ]]; then
  export QS_LIVE_J2_HTTP_ENV_ID="${QS_LIVE_J2_HTTP_ENV_ID-c74eb808-acc6-5fc0-9400-7faa69480261}"
  export QS_LIVE_J2_FILE_ENV_ID="${QS_LIVE_J2_FILE_ENV_ID-5d0c6c1e-7a14-4a14-8a14-000000002020}"
else
  # The real market feed: a momentum portfolio on an active replay of the market service
  # (QS_LIVE_REAL_ENV_ID, or the first whose ticks answer), run twice to the same hash
  export QS_LIVE_REAL_FEED="${QS_LIVE_REAL_FEED-1}"
fi
export QS_LIVE_BENCHMARK_ENV_ID="${QS_LIVE_BENCHMARK_ENV_ID-5d0c6c1e-7a14-4a14-8a14-000000000040}"
export QS_LIVE_TIMEOUT_SECONDS="${QS_LIVE_TIMEOUT_SECONDS:-180}"
# A-NFR-02/03, last: 100 run submits (p95 < 800 ms) on 100 reused "live check load NNN"
# portfolios and 100 projection reads (p95 < 2 s); the runs are left to the worker. Empty
# skips it
export QS_LIVE_LOAD="${QS_LIVE_LOAD-1}"
if [[ -z "${QS_LIVE_PASSWORD:-}" ]]; then
  read_secret "$env" TEST_USERS_PASSWORD QS_LIVE_PASSWORD
fi

log "trading live check on $env through $QS_LIVE_BASE_URL as $QS_LIVE_USERNAME"
# The gateway address (host.docker.internal) must resolve inside the check's container
# too; host-gateway maps it to the Docker host on Linux as Docker Desktop does
run_in_image "$UV_IMAGE" --add-host host.docker.internal:host-gateway \
  -e QS_LIVE_BASE_URL -e QS_LIVE_ENV_ID -e QS_LIVE_USERNAME -e QS_LIVE_VIEWER_USERNAME \
  -e QS_LIVE_QUANT_USERNAME -e QS_LIVE_J2_HTTP_ENV_ID -e QS_LIVE_J2_FILE_ENV_ID -e QS_LIVE_BENCHMARK_ENV_ID -e QS_LIVE_LOAD \
  -e QS_LIVE_REAL_FEED -e QS_LIVE_REAL_ENV_ID \
  -e QS_LIVE_PASSWORD -e QS_LIVE_TIMEOUT_SECONDS -- \
  python -I -B -u ci/scripts/trading_live_check.py \
  || die "trading live check failed on $env"
log "trading live check passed on $env"
