#!/usr/bin/env bash
# Shared helpers for the CI scripts. Source it, do not run it.
#
# Settings read from the environment:
#   IMAGE_PREFIX     registry and name prefix, e.g. ghcr.io/ali-mazhar05/quantsim
#   QS_LOCAL=1       work against the local Docker daemon only (no registry), for laptop runs
#   QS_RELEASES_DIR  where known-good releases are recorded per environment
#
# The variables defined here are used by the scripts that source this file.
# shellcheck disable=SC2034

set -euo pipefail

# Git Bash on Windows rewrites paths such as /tmp in docker arguments; stop it.
export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && (pwd -W 2>/dev/null || pwd))"
COMPONENTS_FILE="$REPO_ROOT/ci/components.conf"
COMPOSE_FILE="$REPO_ROOT/deploy/compose/docker-compose.yml"
IMAGE_PREFIX="${IMAGE_PREFIX:-quantsim}"
QS_LOCAL="${QS_LOCAL:-0}"
QS_RELEASES_DIR="${QS_RELEASES_DIR:-$HOME/.quantsim/releases}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

require_env() {
  local name
  for name in "$@"; do
    [[ -n "${!name:-}" ]] || die "environment variable $name is required"
  done
}

# retry <attempts> <delay-seconds> <command...>
retry() {
  local attempts=$1 delay=$2 n=1
  shift 2
  until "$@"; do
    if (( n >= attempts )); then
      return 1
    fi
    log "attempt $n/$attempts failed, retrying in ${delay}s"
    sleep "$delay"
    n=$((n + 1))
  done
}

# Component registry (ci/components.conf): name kind dockerfile context paths...
component_names() {
  awk '!/^[[:space:]]*(#|$)/ {print $1}' "$COMPONENTS_FILE"
}

component_field() {
  local name=$1 field=$2
  awk -v n="$name" -v f="$field" '!/^[[:space:]]*(#|$)/ && $1 == n {print $f; found=1} END {exit !found}' "$COMPONENTS_FILE" \
    || die "unknown component: $name"
}

component_paths() {
  local name=$1
  awk -v n="$name" '!/^[[:space:]]*(#|$)/ && $1 == n {for (i = 5; i <= NF; i++) print $i}' "$COMPONENTS_FILE"
}

# FRONTEND, MARKET_DATA, ... used for variable names in release files
component_var() {
  printf '%s' "$1" | tr '[:lower:]-' '[:upper:]_'
}

# Absolute path of an existing file, in a form both bash and the docker CLI accept
# (C:/... on Windows, /... elsewhere)
abs_path() {
  local dir
  dir="$(cd "$(dirname "$1")" && { pwd -W 2>/dev/null || pwd; })"
  printf '%s/%s' "$dir" "$(basename "$1")"
}

image_repo() { printf '%s-%s' "$IMAGE_PREFIX" "$1"; }

project_version() {
  tr -d '[:space:]' < "$REPO_ROOT/VERSION"
}

env_file() {
  local env=$1 file="$REPO_ROOT/deploy/env/$1.env"
  [[ -f "$file" ]] || die "no settings file for environment '$env' ($file)"
  printf '%s' "$file"
}

# Loads deploy/env/<env>.env into the current shell
load_env() {
  local file
  file="$(env_file "$1")"
  set -a
  # shellcheck disable=SC1090
  source <(tr -d '\r' < "$file")
  set +a
}

# Loads a release file written by make-release.sh
load_release() {
  local file=$1
  [[ -f "$file" ]] || die "release file not found: $file"
  set -a
  # shellcheck disable=SC1090
  source <(tr -d '\r' < "$file")
  set +a
}

# Runs a command in a throwaway container with the repository mounted at the same
# working directory. Inside Jenkins (itself a container) the workspace lives in a
# volume, so the Jenkins container's volumes are shared instead of a bind mount.
#   run_in_image <image> [docker run options...] -- <command...>
run_in_image() {
  local image=$1
  shift
  local -a opts=()
  while (( $# )) && [[ $1 != "--" ]]; do
    opts+=("$1")
    shift
  done
  [[ ${1:-} == "--" ]] && shift

  local -a mount
  local workdir
  if [[ -f /.dockerenv ]]; then
    mount=(--volumes-from "$(hostname)")
    workdir="$REPO_ROOT"
  else
    local host_path
    host_path="$(cd "$REPO_ROOT" && { pwd -W 2>/dev/null || pwd; })"
    mount=(-v "$host_path:/workspace")
    workdir="/workspace"
  fi

  docker run --rm "${mount[@]}" -w "$workdir" -u "$(id -u):$(id -g)" \
    -e HOME=/tmp "${opts[@]}" "$image" "$@"
}

# Pinned toolchain images used by the CI scripts
NODE_IMAGE="node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402"
UV_IMAGE="ghcr.io/astral-sh/uv:0.9-python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58"
REDPANDA_IMAGE="redpandadata/redpanda:v25.2.9@sha256:bd6c35647153a4dbc19507c8037dcca0802484c23e6e5fbb97591a62539e313a"
SOPS_IMAGE="ghcr.io/getsops/sops:v3.13.3-alpine@sha256:ae501277bf742f1662e0f881f43dd8fd6798b489a8058e921dbf6cda597140ea"
TIMESCALE_IMAGE="timescale/timescaledb:2.22.1-pg17@sha256:fba60021a224479e174ae1ec577c1a0576d5185b09fe9e622f1d19e4bf5bab0d"

# A name unique to this build, safe for Docker objects
build_id() {
  printf '%s' "${BUILD_TAG:-local-$$}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_.-]/-/g'
}

# Cloudflare Pages API: cf_pages_api <METHOD> <path under /pages/projects> [json-body]
cf_pages_api() {
  local method=$1 path=$2 body=${3:-}
  require_env CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID
  local -a args=(-sS -X "$method" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json")
  [[ -n "$body" ]] && args+=(--data "$body")
  curl "${args[@]}" "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects$path"
}

# Public URL of an environment hosted on Cloudflare Pages. The production branch is
# served at the project's own subdomain, every other branch at <branch>.<subdomain>.
pages_url() {
  require_env PAGES_PROJECT PAGES_BRANCH PAGES_PRODUCTION_BRANCH
  local subdomain alias
  subdomain="$(cf_pages_api GET "/$PAGES_PROJECT" | jq -r '.result.subdomain // empty')"
  [[ -n "$subdomain" ]] || die "Cloudflare Pages project $PAGES_PROJECT not found"
  if [[ "$PAGES_BRANCH" == "$PAGES_PRODUCTION_BRANCH" ]]; then
    printf 'https://%s' "$subdomain"
  else
    alias="$(printf '%s' "$PAGES_BRANCH" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g')"
    printf 'https://%s.%s' "$alias" "$subdomain"
  fi
}
