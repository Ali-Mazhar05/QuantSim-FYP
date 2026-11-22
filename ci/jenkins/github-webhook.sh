#!/usr/bin/env bash
# Points the quantsim-jenkins GitHub App's webhook at Jenkins' current public address, so
# pushes and merges start builds at once instead of waiting for the next branch scan.
# The quick tunnel gets a new https://<random>.trycloudflare.com address whenever it
# restarts; host.sh start runs this with the new one, and `host.sh webhook` runs it again.
#
#   ci/jenkins/github-webhook.sh <public Jenkins URL>
#
# Signs a short-lived GitHub App token (JWT, RS256) with secrets/github_app_key and
# secrets/github_app_id, then sets the app's webhook URL (PATCH /app/hook/config). Only
# the URL changes: the webhook's secret and its Active setting stay as they are.
# Needs openssl and curl on this machine. Prints nothing secret.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
secrets="$here/secrets"
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

url="${1:?usage: github-webhook.sh <public Jenkins URL>}"
url="${url%/}"
case "$url" in
  https://*) ;;
  *) die "GitHub only delivers to a public https address, not $url" ;;
esac
for tool in openssl curl; do
  command -v "$tool" >/dev/null || die "$tool is not installed on this machine"
done
for name in github_app_id github_app_key; do
  [[ -s "$secrets/$name" ]] || die "missing ci/jenkins/secrets/$name (see secrets/README.md)"
done

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

app_id="$(tr -d '\r\n ' < "$secrets/github_app_id")"
now="$(date +%s)"
# Issued a minute in the past against clock drift; GitHub allows at most ten minutes
header="$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)"
payload="$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "$((now - 60))" "$((now + 540))" "$app_id" | b64url)"
signature="$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -sign "$secrets/github_app_key" -binary | b64url)"
jwt="$header.$payload.$signature"

hook="$url/github-webhook/"
status="$(curl -s -o /dev/null -w '%{http_code}' -X PATCH https://api.github.com/app/hook/config \
  -H "Authorization: Bearer $jwt" \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  -d "{\"url\":\"$hook\",\"content_type\":\"json\"}")"
[[ "$status" == 200 ]] || die "GitHub refused the webhook update (HTTP $status)"
log "the GitHub webhook now delivers to $hook"
