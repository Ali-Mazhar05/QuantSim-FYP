#!/usr/bin/env bash
# Deploys a release file to an environment.
#   usage: deploy.sh <env> <release-file>
#
# deploy/env/<env>.env decides where things go:
#   COMPOSE_TARGET   local (this Docker host), ssh://user@host (a remote server), or none
#   FRONTEND_TARGET  compose (served by nginx behind Traefik) or pages (Cloudflare Pages)
#
# Secrets in deploy/secrets/<env>.enc.env are decrypted with SOPS into a temporary
# file for the duration of the deploy only (needs SOPS_AGE_KEY_FILE).
source "$(dirname "$0")/lib.sh"

env="${1:?usage: deploy.sh <env> <release-file>}"
release="${2:?usage: deploy.sh <env> <release-file>}"
release="$(cd "$(dirname "$release")" && pwd)/$(basename "$release")"

load_env "$env"
load_release "$release"
require_env QS_PROJECT COMPOSE_TARGET FRONTEND_TARGET

secrets_args=()
encrypted="$REPO_ROOT/deploy/secrets/$env.enc.env"
if [[ -f "$encrypted" ]]; then
  require_env SOPS_AGE_KEY_FILE
  secrets_file="$(mktemp)"
  trap 'rm -f "$secrets_file"' EXIT
  sops --decrypt --input-type dotenv --output-type dotenv "$encrypted" > "$secrets_file"
  secrets_args=(--env-file "$secrets_file")
fi

if [[ "$COMPOSE_TARGET" != "none" ]]; then
  if [[ "$COMPOSE_TARGET" == ssh://* ]]; then
    export DOCKER_HOST="$COMPOSE_TARGET"
  fi

  profiles=()
  [[ "$FRONTEND_TARGET" == "compose" ]] && profiles+=(--profile frontend)

  compose=(docker compose -p "$QS_PROJECT" -f "$COMPOSE_FILE"
           --env-file "$(env_file "$env")" --env-file "$release" "${secrets_args[@]}")

  if [[ "$QS_LOCAL" != "1" ]]; then
    log "pulling images for $QS_PROJECT"
    "${compose[@]}" "${profiles[@]}" pull --quiet
  fi

  # Each backend service may define a one-off <name>-migrate container in the
  # "migrate" profile; it runs to completion before the new version starts.
  mapfile -t migrators < <("${compose[@]}" --profile migrate config --services | grep -- '-migrate$' || true)
  for migrator in "${migrators[@]}"; do
    log "running database migrations: $migrator"
    "${compose[@]}" --profile migrate run --rm "$migrator"
  done

  log "starting $QS_PROJECT"
  "${compose[@]}" "${profiles[@]}" up -d --wait --wait-timeout 180 --remove-orphans
fi

if [[ "$FRONTEND_TARGET" == "pages" ]]; then
  "$(dirname "$0")/pages-deploy.sh" "$env" "$release"
fi

log "deployed release $QS_RELEASE_VERSION ($QS_RELEASE_GIT_SHA) to $env"
