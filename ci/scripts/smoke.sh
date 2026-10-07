#!/usr/bin/env bash
# Confirms an environment is up and serving exactly the release that was deployed.
#   usage: smoke.sh <env> <release-file>
#
# Frontend: /version.json must report the release's content hash, and the app shell
# must load. Backend services: /api/<name>/health through the gateway must answer
# 200, and report the release's content hash when it includes one.
source "$(dirname "$0")/lib.sh"

env="${1:?usage: smoke.sh <env> <release-file>}"
release="${2:?usage: smoke.sh <env> <release-file>}"

load_env "$env"
load_release "$release"

ATTEMPTS="${SMOKE_ATTEMPTS:-20}"
DELAY="${SMOKE_DELAY:-3}"

body_of() { curl -fsS --max-time 10 "$1"; }

reports_hash() {
  local url=$1 expected=$2 body
  body="$(body_of "$url")" || return 1
  if grep -q '"content_hash"' <<<"$body"; then
    grep -q "\"content_hash\":\"$expected\"" <<<"$body" || {
      log "$url reports a different build: $body"
      return 1
    }
  fi
}

serves_app_shell() { body_of "$1/" | grep -q 'id="root"'; }

check_frontend() {
  local base=$1
  log "checking frontend at $base"
  if [[ "$FRONTEND_TARGET" == "compose" ]]; then
    retry "$ATTEMPTS" "$DELAY" body_of "$base/healthz" >/dev/null || die "frontend health check failed"
  fi
  retry "$ATTEMPTS" "$DELAY" reports_hash "$base/version.json" "$FRONTEND_HASH" \
    || die "frontend is not serving content hash $FRONTEND_HASH"
  retry "$ATTEMPTS" "$DELAY" serves_app_shell "$base" || die "frontend app shell did not load"
  log "frontend OK ($FRONTEND_HASH)"
}

case "$FRONTEND_TARGET" in
  compose) require_env SMOKE_BASE_URL; check_frontend "$SMOKE_BASE_URL" ;;
  pages)   check_frontend "$(pages_url)" ;;
  *)       die "unknown FRONTEND_TARGET: $FRONTEND_TARGET" ;;
esac

if [[ "$COMPOSE_TARGET" != "none" ]]; then
  require_env SMOKE_BASE_URL
  while read -r name; do
    [[ "$(component_field "$name" 2)" == "service" ]] || continue
    var="$(component_var "$name")_HASH"
    url="$SMOKE_BASE_URL/api/$name/health"
    log "checking service $name at $url"
    retry "$ATTEMPTS" "$DELAY" reports_hash "$url" "${!var}" || die "service $name failed its health check"
    log "service $name OK (${!var})"
  done < <(component_names)
fi

log "smoke test passed for $env"
