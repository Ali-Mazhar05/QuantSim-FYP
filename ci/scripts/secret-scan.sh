#!/usr/bin/env bash
# Fails if a commit adds something that looks like a secret (C-NFR-12), using a pinned
# gitleaks with its default rules. Real secrets live only in deploy/secrets/*.enc.env,
# encrypted with SOPS, which gitleaks does not flag.
#   usage: secret-scan.sh [<base branch>]
# With a base branch (a pull request's target) only the commits not yet on it are scanned;
# without one, or when the base is not fetched, the whole history is (a few minutes).
source "$(dirname "$0")/lib.sh"

GITLEAKS_IMAGE="ghcr.io/gitleaks/gitleaks:v8.18.4@sha256:75bdb2b2f4db213cde0b8295f13a88d6b333091bbfbf3012a4e083d00d31caba"

cd "$REPO_ROOT"

base="${1:-}"
range=()
if [[ -n "$base" ]] && git rev-parse --verify --quiet "origin/$base" >/dev/null; then
  range=(--log-opts="origin/$base..HEAD")
  log "scanning the commits not on $base"
else
  log "scanning the whole history"
fi

# The container runs as the CI user, so git must trust the mounted checkout
run_in_image "$GITLEAKS_IMAGE" \
  -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' -- \
  detect --source . "${range[@]}" --redact --no-banner \
  || die "possible secret committed; see the findings above (values are redacted)"
log "no secrets found"
