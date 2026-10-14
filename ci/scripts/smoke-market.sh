#!/usr/bin/env bash
# Smoke test of the market data service, called by smoke.sh after the generic health check.
#   usage: smoke-market.sh <env>        (deploy/env/<env>.env is loaded for the settings)
#
# 1. /api/market/ready through the gateway: database and Redis reachable.
# 2. Only where the fixture vendor is configured (MARKET_VENDOR=fixture, DEV) and the
#    stack is on this Docker host: seed the instrument master, run one manual run of AAPL
#    over the recorded window, and check the run report. The run goes through the API when
#    SMOKE_ADMIN_USER and SMOKE_ADMIN_PASSWORD are set (an admin login), otherwise through
#    `python -m qs_market run-once` in the market container, which exercises the same
#    pipeline, database and vendor adapter without needing a token.
# Environments with the real vendor stop after step 1: a smoke test must not spend the
# shared Tiingo budget.
source "$(dirname "$0")/lib.sh"

env="${1:?usage: smoke-market.sh <env>}"
load_env "$env"
require_env SMOKE_BASE_URL

ATTEMPTS="${SMOKE_ATTEMPTS:-20}"
DELAY="${SMOKE_DELAY:-3}"
base="$SMOKE_BASE_URL/api/market"
start="2024-01-02"
end="2024-02-13"

ready() { curl -fsS --max-time 10 "$base/ready" | grep -q '"status":"ready"'; }
log "checking $base/ready"
retry "$ATTEMPTS" "$DELAY" ready || die "market service is not ready (database or Redis unreachable)"
log "market ready"

if [[ "${MARKET_VENDOR:-fixture}" != "fixture" ]]; then
  log "market vendor is ${MARKET_VENDOR}, skipping the manual run (it would spend the shared budget)"
  exit 0
fi
if [[ "$COMPOSE_TARGET" != "local" ]]; then
  log "market stack is not on this Docker host, skipping the manual run"
  exit 0
fi

container="$QS_PROJECT-market-1"
inside() { docker exec "$container" "$@"; }

log "seeding the instrument master (safe to repeat)"
inside python -m qs_market.seed >/dev/null || die "seeding the instrument master failed"

# Reads a run report (JSON) on stdin: the run must have succeeded
report_succeeded() {
  local body
  body="$(cat)"
  grep -Eq '"status": ?"succeeded"' <<<"$body" || {
    log "run report: ${body:0:600}"
    return 1
  }
}

if [[ -n "${SMOKE_ADMIN_USER:-}" && -n "${SMOKE_ADMIN_PASSWORD:-}" ]]; then
  log "manual run through the API as $SMOKE_ADMIN_USER"
  login_body="$(printf '{"username":"%s","password":"%s"}' "$SMOKE_ADMIN_USER" "$SMOKE_ADMIN_PASSWORD")"
  token="$(curl -fsS --max-time 10 -H 'Content-Type: application/json' -d "$login_body" \
    "$SMOKE_BASE_URL/api/platform/auth/login" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')"
  [[ -n "$token" ]] || die "could not sign in as $SMOKE_ADMIN_USER"
  auth=(-H "Authorization: Bearer $token")
  accepted="$(curl -fsS --max-time 10 "${auth[@]}" -H 'Content-Type: application/json' \
    -d "{\"mode\":\"manual\",\"start\":\"$start\",\"end\":\"$end\",\"symbols\":[\"AAPL\"]}" \
    "$base/ingestion-runs")" || die "the manual run was refused"
  run_id="$(sed -n 's/.*"id":"\([^"]*\)".*/\1/p' <<<"$accepted")"
  [[ -n "$run_id" ]] || die "the API did not return a run id: $accepted"
  finished() {
    local body
    body="$(curl -fsS --max-time 10 "${auth[@]}" "$base/ingestion-runs/$run_id")" || return 1
    grep -Eq '"status":"(succeeded|partially_succeeded|failed)"' <<<"$body"
  }
  retry 40 3 finished || die "run $run_id did not finish"
  curl -fsS --max-time 10 "${auth[@]}" "$base/ingestion-runs/$run_id" | check_report "$run_id" \
    || die "run $run_id did not succeed"
else
  log "manual run in the market container (set SMOKE_ADMIN_USER and SMOKE_ADMIN_PASSWORD to go through the API)"
  # Exit code 3 means the worker holds the run lock at that moment; try again
  report=""
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    code=0
    report="$(inside python -m qs_market run-once --mode manual --symbol AAPL --start "$start" --end "$end")" || code=$?
    [[ "$code" == 3 ]] || break
    log "worker is busy, retrying ($attempt/10)"
    sleep "$DELAY"
  done
  [[ "$code" == 0 ]] || die "the manual run failed (exit $code)"
  report_succeeded <<<"$report" || die "the manual run did not succeed"
fi

log "market smoke test passed"
