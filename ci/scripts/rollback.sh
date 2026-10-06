#!/usr/bin/env bash
# Puts an environment back on a recorded release and smoke tests it.
#   usage: rollback.sh <env> [current|previous]
#
#   current   the last release that passed its smoke test (default). After a failed
#             deploy this is the version that was running before it.
#   previous  the release before that, for undoing a deploy that passed its smoke
#             test but turned out to be bad.
source "$(dirname "$0")/lib.sh"

env="${1:?usage: rollback.sh <env> [current|previous]}"
which="${2:-current}"

recorded="$QS_RELEASES_DIR/$env/$which.env"
[[ -f "$recorded" ]] || die "no $which release recorded for $env; nothing to roll back to"

# Work from a copy: recording a rollback to "previous" rotates the recorded files
release="$(mktemp)"
trap 'rm -f "$release"' EXIT
cp "$recorded" "$release"

log "rolling $env back to $(grep '^QS_RELEASE_GIT_SHA=' "$release" | cut -d= -f2)"
"$(dirname "$0")/deploy.sh" "$env" "$release"
"$(dirname "$0")/smoke.sh" "$env" "$release"

if [[ "$which" == "previous" ]]; then
  "$(dirname "$0")/record-release.sh" "$env" "$release"
fi

log "rollback of $env complete"
