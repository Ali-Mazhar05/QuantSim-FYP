#!/usr/bin/env bash
# Posts a commit status to GitHub. Branch protection requires these statuses on a
# promotion pull request, so a commit can only move to the next environment after
# it has proven itself in the previous one.
#   usage: github-status.sh <context> <success|failure|pending|error> <description> [sha]
#   needs: GITHUB_TOKEN, GITHUB_REPO (owner/name); BUILD_URL is linked when set
source "$(dirname "$0")/lib.sh"

context="${1:?usage: github-status.sh <context> <state> <description> [sha]}"
state="${2:?usage: github-status.sh <context> <state> <description> [sha]}"
description="${3:?usage: github-status.sh <context> <state> <description> [sha]}"
sha="${4:-$(git -C "$REPO_ROOT" rev-parse HEAD)}"

require_env GITHUB_TOKEN GITHUB_REPO

payload="$(jq -n --arg state "$state" --arg context "$context" \
  --arg description "${description:0:140}" --arg target_url "${BUILD_URL:-}" \
  '{state: $state, context: $context, description: $description}
   + (if $target_url == "" then {} else {target_url: $target_url} end)')"

response="$(mktemp)"
trap 'rm -f "$response"' EXIT
code="$(curl -sS -o "$response" -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  --data "$payload" \
  "https://api.github.com/repos/$GITHUB_REPO/statuses/$sha")"

[[ "$code" == "201" ]] || die "GitHub rejected the $context status (HTTP $code): $(cat "$response")"
log "posted $context=$state on ${sha:0:12}"
