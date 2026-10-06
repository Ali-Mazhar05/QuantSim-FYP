#!/usr/bin/env bash
# Writes the release file for an environment: the exact image of every component.
# The same file drives the deploy, the smoke test and any later rollback.
#   usage: make-release.sh <env> <output-file>
source "$(dirname "$0")/lib.sh"

env="${1:?usage: make-release.sh <env> <output-file>}"
out="${2:?usage: make-release.sh <env> <output-file>}"
mkdir -p "$(dirname "$out")"

{
  echo "QS_RELEASE_ENV=$env"
  echo "QS_RELEASE_VERSION=$(project_version)"
  echo "QS_RELEASE_GIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)"
  echo "QS_RELEASE_CREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  while read -r name; do
    hash="$("$(dirname "$0")/content-hash.sh" "$name")"
    var="$(component_var "$name")"
    echo "${var}_HASH=$hash"
    echo "${var}_IMAGE=$(image_repo "$name"):$hash"
  done < <(component_names)
} > "$out"

log "release for $env written to $out"
cat "$out" >&2
