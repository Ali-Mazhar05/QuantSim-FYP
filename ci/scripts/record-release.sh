#!/usr/bin/env bash
# Records a release that passed its smoke test as the environment's known-good state.
# The release it replaces is kept as previous.env for manual rollbacks.
#   usage: record-release.sh <env> <release-file>
source "$(dirname "$0")/lib.sh"

env="${1:?usage: record-release.sh <env> <release-file>}"
release="${2:?usage: record-release.sh <env> <release-file>}"

dir="$QS_RELEASES_DIR/$env"
mkdir -p "$dir"

[[ -f "$dir/current.env" ]] && mv "$dir/current.env" "$dir/previous.env"
cp "$release" "$dir/current.env"

log "recorded $(grep '^QS_RELEASE_GIT_SHA=' "$release" | cut -d= -f2) as the known-good release of $env"
