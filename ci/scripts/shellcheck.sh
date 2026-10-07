#!/usr/bin/env bash
# Lints the CI scripts themselves with a pinned ShellCheck.
#   usage: shellcheck.sh
source "$(dirname "$0")/lib.sh"

SHELLCHECK_IMAGE="koalaman/shellcheck:stable@sha256:bb596a0d169b85ddd81d8b6d3a2ff6d5baf5fca10b97f575ebc647c3dff62b3d"

cd "$REPO_ROOT"
run_in_image "$SHELLCHECK_IMAGE" -- -x -P ci/scripts ci/scripts/*.sh
log "CI scripts pass ShellCheck"
