#!/usr/bin/env bash
# Keeps the public addresses of the machine hosting Jenkins working, without a person.
# Run every few minutes by the quantsim-tunnel-watchdog timer (install-tunnel-watchdog.sh);
# safe to run by hand at any time:
#
#   ci/jenkins/tunnel-watchdog.sh            check and heal
#   ci/jenkins/tunnel-watchdog.sh --dry-run  only report what it would do
#
# DEV, TEST, ACC and PROD each reach the internet through a Cloudflare quick tunnel
# (api-tunnel), and Jenkins through its own (tunnel). A quick tunnel's address is random,
# changes on every restart and can disappear at any time (22-23 Nov: Cloudflare dropped
# them overnight, and every website then called an address that no longer existed). For
# each tunnel this script:
#
#   1. reads the tunnel's current address and checks it answers: the name resolves and at
#      least one of its Cloudflare addresses returns the health page (this network cannot
#      reach every Cloudflare address, so each is tried on its own);
#   2. when it does not answer on two runs in a row, restarts that tunnel, which gets a new
#      address (a tunnel restarted in the last 5 minutes, e.g. by a deploy, is left alone);
#   3. when the address works but is not the one published, publishes it: the environment's
#      website config.json (from the release recorded for it; no rebuild, no approval), or
#      for Jenkins the GitHub webhook and the link in Jenkins' build statuses (Jenkins is
#      restarted for that only while no build runs).
#
# Needs: Docker, the secrets in ci/jenkins/secrets (cloudflare_api_token,
# cloudflare_account_id, github_app_id, github_app_key, admin_password) and curl. Logs one
# line per action, nothing when all is well (unless QS_WATCHDOG_VERBOSE=1).
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
secrets="$here/secrets"
project="${QS_JENKINS_PROJECT:-quantsim-jenkins}"
agent="$project-agent-1"
state="${QS_WATCHDOG_STATE:-$HOME/.quantsim/watchdog}"
dry_run=0
[[ "${1:-}" == "--dry-run" ]] && dry_run=1
verbose="${QS_WATCHDOG_VERBOSE:-0}"
# A tunnel younger than this was just (re)started, by a deploy or by this script
settle_seconds=300
# Consecutive failed checks before a tunnel is restarted
failures_before_restart=2
# Its own cache volume: the Jenkins agent owns qs-ci-cache (another user id)
export CI_CACHE_VOLUME="${CI_CACHE_VOLUME:-qs-ci-cache-host}"

# NODE_IMAGE, load_env and the Pages helpers come from the CI library (which also turns on
# set -e; this script carries on past a failed check instead)
# shellcheck source=../scripts/lib.sh
source "$repo/ci/scripts/lib.sh" || exit 1
set +e

mkdir -p "$state"
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
info() { [[ "$verbose" == 1 ]] && log "$@"; return 0; }
dk() { MSYS_NO_PATHCONV=1 docker "$@"; }

# answers <https-url> <path>: true when the name resolves and one of its addresses answers
answers() {
  local url=$1 path=$2 host address
  host="${url#https://}"; host="${host%%/*}"
  while read -r address; do
    [[ -n "$address" ]] || continue
    if curl -s -o /dev/null -m 10 --resolve "$host:443:$address" -w '%{http_code}' "https://$host$path" \
      | grep -qE '^[234][0-9][0-9]$'; then
      return 0
    fi
  done < <(getent ahostsv4 "$host" 2>/dev/null | awk '{print $1}' | sort -u)
  return 1
}

# tunnel_url <docker network> <tunnel service name>: the tunnel's current public address
tunnel_url() {
  dk run --rm --network "$1" --entrypoint wget "${NODE_IMAGE}" -qO- --timeout=5 \
    "http://$2:2000/quicktunnel" 2>/dev/null \
    | sed -n 's/.*"hostname":"\([^"]*\)".*/https:\/\/\1/p' || true
}

# age_seconds <container>: seconds since the container last started
age_seconds() {
  local started
  started="$(dk inspect --format '{{.State.StartedAt}}' "$1" 2>/dev/null)" || { echo 0; return; }
  echo $(( $(date +%s) - $(date -d "$started" +%s 2>/dev/null || date +%s) ))
}

# failed <key>: counts a failed check, true once it reached the restart threshold
failed() {
  local file="$state/$1.failures" count
  count=$(( $(cat "$file" 2>/dev/null || echo 0) + 1 ))
  echo "$count" > "$file"
  (( count >= failures_before_restart ))
}
recovered() { rm -f "$state/$1.failures"; }

# restart <key> <container>: restarts a tunnel unless it just started
restart() {
  local key=$1 container=$2
  if (( $(age_seconds "$container") < settle_seconds )); then
    info "$key: $container started less than $settle_seconds s ago; waiting for it"
    return 1
  fi
  log "$key: the tunnel's address does not answer; restarting $container for a new one"
  (( dry_run )) && return 1
  dk restart "$container" >/dev/null && recovered "$key"
}

# --- Environments -----------------------------------------------------------------------

site_for() { # site_for <env>: the website address the environment publishes to
  ( load_env "$1"
    export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID
    pages_url ) 2>/dev/null
}

publish_site() { # publish_site <env>: republish the website with the current API address
  local env=$1 release
  release="$(mktemp)"
  if ! dk exec "$agent" cat "/home/jenkins/agent/releases/$env/current.env" > "$release" 2>/dev/null; then
    log "$env: no release is recorded for it on the Jenkins agent; deploy it once from Jenkins"
    rm -f "$release"; return 1
  fi
  if (( dry_run )); then log "$env: would republish its website"; rm -f "$release"; return 0; fi
  if QS_LOCAL=1 "$repo/ci/scripts/pages-deploy.sh" "$env" "$release" >"$state/$env.publish.log" 2>&1; then
    log "$env: website republished with $(grep -o 'the API at [^ ]*' "$state/$env.publish.log" | tail -1)"
  else
    log "$env: republishing its website failed; see $state/$env.publish.log"
  fi
  rm -f "$release"
}

CLOUDFLARE_API_TOKEN="$(tr -d '\r\n' < "$secrets/cloudflare_api_token" 2>/dev/null)"
CLOUDFLARE_ACCOUNT_ID="$(tr -d '\r\n' < "$secrets/cloudflare_account_id" 2>/dev/null)"
export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID

for env in dev test acc prod; do
  qs_project="qs-$env"
  container="$qs_project-api-tunnel-1"
  dk inspect "$container" >/dev/null 2>&1 || { info "$env: not deployed on this machine"; continue; }

  url="$(tunnel_url "${qs_project}_default" api-tunnel)"
  if [[ -z "$url" ]] || ! answers "$url" /api/platform/health; then
    info "$env: ${url:-no address} does not answer"
    failed "$env" && restart "$env" "$container"
    continue
  fi
  recovered "$env"

  site="$(site_for "$env")"
  [[ -n "$site" ]] || { info "$env: cannot tell its website address"; continue; }
  published="$(curl -s -m 15 "$site/config.json?watchdog=$(date +%s)" \
    | sed -n 's#.*"apiBaseUrl" *: *"\([^"]*\)".*#\1#p')"
  if [[ "${published%/}" != "${url%/}" ]]; then
    log "$env: the website calls ${published:-nothing}, the API is at $url"
    publish_site "$env"
  else
    info "$env: $url answers and is published"
  fi
done

# --- Jenkins ----------------------------------------------------------------------------

jenkins_idle() { # no build is running
  local password busy
  password="$(tr -d '\r\n' < "$secrets/admin_password" 2>/dev/null)" || return 1
  busy="$(curl -s -m 10 -u "admin:$password" \
    "http://localhost:${JENKINS_PORT:-8080}/computer/api/json?tree=busyExecutors" \
    | sed -n 's/.*"busyExecutors":\([0-9]*\).*/\1/p')"
  [[ "$busy" == 0 ]]
}

if dk inspect "$project-tunnel-1" >/dev/null 2>&1; then
  url="$(tunnel_url "${project}_default" tunnel)"
  if [[ -z "$url" ]] || ! answers "$url" /login; then
    info "jenkins: ${url:-no address} does not answer"
    failed jenkins && restart jenkins "$project-tunnel-1"
  else
    recovered jenkins
    url="${url%/}"
    # The GitHub webhook, once per new address
    if [[ "$(cat "$state/jenkins.webhook" 2>/dev/null)" != "$url" ]]; then
      if (( dry_run )); then
        log "jenkins: would point the GitHub webhook at $url"
      elif "$here/github-webhook.sh" "$url" >"$state/jenkins.webhook.log" 2>&1; then
        echo "$url" > "$state/jenkins.webhook"
        log "jenkins: the GitHub webhook now delivers to $url/github-webhook/"
      else
        log "jenkins: could not update the GitHub webhook; see $state/jenkins.webhook.log"
      fi
    fi
    # The link Jenkins puts in GitHub statuses (JENKINS_URL), applied while no build runs
    env_file="$here/.env"
    current="$(sed -n 's/^JENKINS_URL=//p' "$env_file" 2>/dev/null | tr -d '\r' | tail -1)"
    if [[ -f "$env_file" && "${current%/}" != "$url" ]]; then
      if (( dry_run )); then
        log "jenkins: would set JENKINS_URL to $url/"
      elif jenkins_idle; then
        sed -i.bak "s#^JENKINS_URL=.*#JENKINS_URL=$url/#" "$env_file" && rm -f "$env_file.bak"
        if docker compose -p "$project" -f "$here/compose.yml" --profile shared --profile tunnel \
          up -d jenkins >/dev/null 2>&1; then
          log "jenkins: build links now use $url/ (Jenkins restarted while idle)"
        else
          log "jenkins: JENKINS_URL is set to $url/ but Jenkins did not restart"
        fi
      else
        info "jenkins: builds are running; JENKINS_URL is updated on a later run"
      fi
    fi
  fi
fi
exit 0
