#!/usr/bin/env bash
# Deploys a release file to an environment.
#   usage: deploy.sh <env> <release-file>
#
# deploy/env/<env>.env decides where things go:
#   COMPOSE_TARGET   local (this Docker host), ssh://user@host (a remote server), or none
#   FRONTEND_TARGET  compose (served by nginx behind Traefik) or pages (Cloudflare Pages)
#
# Secrets in deploy/secrets/<env>.enc.env are decrypted with a pinned SOPS container
# into a temporary file that exists only for the duration of the deploy.
# Needs SOPS_AGE_KEY_FILE: the age private key of Jenkins or of a team member.
source "$(dirname "$0")/lib.sh"

env="${1:?usage: deploy.sh <env> <release-file>}"
release="${2:?usage: deploy.sh <env> <release-file>}"
[[ -f "$release" ]] || die "release file not found: $release"
release="$(abs_path "$release")"

load_env "$env"
load_release "$release"
require_env QS_PROJECT COMPOSE_TARGET FRONTEND_TARGET

secrets_args=()
encrypted="deploy/secrets/$env.enc.env"
if [[ -f "$REPO_ROOT/$encrypted" ]]; then
  require_env SOPS_AGE_KEY_FILE
  secrets_file="$(mktemp)"
  trap 'rm -f "$secrets_file"' EXIT
  secrets_file="$(abs_path "$secrets_file")"
  SOPS_AGE_KEY="$(cat "$SOPS_AGE_KEY_FILE")" run_in_image "$SOPS_IMAGE" -e SOPS_AGE_KEY -- \
    --decrypt --input-type dotenv --output-type dotenv "$encrypted" > "$secrets_file" \
    || die "could not decrypt $encrypted; is SOPS_AGE_KEY_FILE one of the keys in .sops.yaml?"
  secrets_args=(--env-file "$secrets_file")
fi

if [[ "$COMPOSE_TARGET" != "none" ]]; then
  if [[ "$COMPOSE_TARGET" == ssh://* ]]; then
    export DOCKER_HOST="$COMPOSE_TARGET"
  fi

  profiles=()
  [[ "$FRONTEND_TARGET" == "compose" ]] && profiles+=(--profile frontend)
  [[ "${MAILPIT:-false}" == "true" ]] && profiles+=(--profile mailpit)
  # One market scheduler for all environments: only where deploy/env/<env>.env enables it
  [[ "${QS_INGEST_SCHEDULER_ENABLED:-false}" == "true" ]] && profiles+=(--profile scheduler)

  compose=(docker compose -p "$QS_PROJECT" -f "$COMPOSE_FILE"
           --env-file "$(env_file "$env")" --env-file "$release" "${secrets_args[@]}")

  if [[ "$QS_LOCAL" != "1" ]]; then
    log "pulling images for $QS_PROJECT"
    "${compose[@]}" "${profiles[@]}" pull --quiet
  fi

  "${compose[@]}" config --quiet || die "the compose configuration for $env is invalid"

  # Each backend service may define a one-off <name>-migrate container in the
  # "migrate" profile; it runs to completion before the new version starts.
  mapfile -t migrators < <("${compose[@]}" --profile migrate config --services | grep -- '-migrate$' || true)
  for migrator in "${migrators[@]}"; do
    log "running database migrations: $migrator"
    "${compose[@]}" --profile migrate run --rm "$migrator"
  done

  log "starting $QS_PROJECT"
  "${compose[@]}" "${profiles[@]}" up -d --wait --wait-timeout 180 --remove-orphans

  # The website reads this address from its config.json (pages-deploy.sh)
  API_PUBLIC_URL="$(wait_for_api_url "$QS_PROJECT")" \
    || die "the API of $env has no public address; check the $QS_PROJECT-api-tunnel-1 logs"
  export API_PUBLIC_URL
  log "public API address of $env: $API_PUBLIC_URL"
fi

if [[ "$FRONTEND_TARGET" == "pages" ]]; then
  "$(dirname "$0")/pages-deploy.sh" "$env" "$release"
fi

log "deployed release $QS_RELEASE_VERSION ($QS_RELEASE_GIT_SHA) to $env"
