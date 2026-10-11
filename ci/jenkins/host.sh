#!/usr/bin/env bash
# Shared hosting of QuantSim Jenkins: any team member can host it, one at a time, and
# Jenkins stays the same whoever runs it. Its state (job history, build numbers,
# recorded releases used for rollback) is handed over through Cloudflare R2, a host
# lease stops two machines running Jenkins at once, and DEV and TEST are redeployed on
# the new host from the same images.
#
#   ci/jenkins/host.sh status            who hosts Jenkins now, and its link
#   ci/jenkins/host.sh start [--force]   take over: fetch the latest state, start Jenkins
#   ci/jenkins/host.sh stop              hand back: stop Jenkins, upload its state
#
# Needs: Docker, ci/jenkins/init-env.sh run once on this machine, and the secret files
# r2_access_key_id and r2_secret_access_key (see secrets/README.md).
# QS_JENKINS_PROJECT, QS_STATE_ENDPOINT, QS_STATE_PROVIDER and HOST_ID can be set in the
# environment to run a second, isolated copy (used to test the hand-over).
# --force takes over even if another host's lease is still fresh; use it only when that
# machine is known to be off.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
secrets="$here/secrets"
project="${QS_JENKINS_PROJECT:-quantsim-jenkins}"
compose=(docker compose -p "$project" -f "$here/compose.yml" --profile shared --profile tunnel)
rclone_image="rclone/rclone:1.71@sha256:3103526c506266a9ecdf064efe99bf3677d92ef6407af124d8c56b4f49cbaa51"
volumes=(jenkins_home agent_home)
fresh_seconds=600

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

# Git Bash on Windows would rewrite the container paths below
dk() { MSYS_NO_PATHCONV=1 docker "$@"; }

[[ -f "$here/.env" ]] || die "run ci/jenkins/init-env.sh on this machine first"
env_value() { sed -n "s/^$1=//p" "$here/.env" | tr -d '\r' | tail -1; }
host_id="${HOST_ID:-$(env_value HOST_ID)}"
bucket="$(env_value QS_STATE_BUCKET)"
bucket="${bucket:-quantsim-ci}"
[[ -n "$host_id" ]] || die "HOST_ID is missing from ci/jenkins/.env; re-run ci/jenkins/init-env.sh"

for name in r2_access_key_id r2_secret_access_key cloudflare_account_id; do
  [[ -s "$secrets/$name" ]] || die "missing ci/jenkins/secrets/$name (see secrets/README.md)"
done
# QS_STATE_ENDPOINT / QS_STATE_PROVIDER point at other S3-compatible storage instead of R2
endpoint="${QS_STATE_ENDPOINT:-https://$(tr -d '\r\n' < "$secrets/cloudflare_account_id").r2.cloudflarestorage.com}"
r2_env=(
  -e RCLONE_CONFIG_R2_TYPE=s3
  -e "RCLONE_CONFIG_R2_PROVIDER=${QS_STATE_PROVIDER:-Cloudflare}"
  -e "RCLONE_CONFIG_R2_ACCESS_KEY_ID=$(tr -d '\r\n' < "$secrets/r2_access_key_id")"
  -e "RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$(tr -d '\r\n' < "$secrets/r2_secret_access_key")"
  -e "RCLONE_CONFIG_R2_ENDPOINT=$endpoint"
  # The R2 token is limited to the one bucket and may not create buckets
  -e RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true
)
remote="r2:$bucket/jenkins"

# r2 [docker run options...] -- <shell command run in the rclone image>
r2() {
  local -a opts=()
  while (( $# )) && [[ $1 != "--" ]]; do opts+=("$1"); shift; done
  shift
  dk run --rm -i "${r2_env[@]}" "${opts[@]}" --entrypoint sh "$rclone_image" -c "$1"
}

read_kv() { sed -n "s/^$1=//p" <<<"$2" | tr -d '\r' | tail -1; }

lease_text() { r2 -- "rclone cat $remote/lease.env 2>/dev/null || true"; }
state_text() { r2 -- "rclone cat $remote/state.env 2>/dev/null || true"; }

local_state_at() {
  dk run --rm -v "${project}_jenkins_home:/data:ro" --entrypoint sh "$rclone_image" \
    -c 'sed -n "s/^at=//p" /data/.quantsim-state 2>/dev/null || true' 2>/dev/null | tr -d '\r' || true
}

ago() { local s=$(( $(date +%s) - $1 )); if (( s < 120 )); then echo "${s}s ago"; else echo "$((s / 60)) min ago"; fi; }

jenkins_running() {
  [[ -n "$(dk ps -q --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=jenkins")" ]]
}

status() {
  local lease owner seen url state
  lease="$(lease_text)"
  owner="$(read_kv host "$lease")"; seen="$(read_kv at "$lease")"; url="$(read_kv url "$lease")"
  if [[ -n "$owner" ]] && (( $(date +%s) - seen < fresh_seconds )); then
    log "Jenkins is hosted by $owner (seen $(ago "$seen")) at $url"
  elif [[ -n "$owner" ]]; then
    log "No one is hosting. $owner was last seen $(ago "$seen") without handing over; it may be off"
  else
    log "No one is hosting Jenkins right now"
  fi
  state="$(state_text)"
  if [[ -n "$state" ]]; then
    log "Latest handed-over state: from $(read_kv host "$state"), $(ago "$(read_kv at "$state")")"
  else
    log "No state has been handed over yet"
  fi
  if jenkins_running; then log "Jenkins is running on this machine ($host_id)"; fi
}

restore_state() {
  local state remote_at local_at
  state="$(state_text)"
  [[ -n "$state" ]] || { log "no handed-over state yet; starting from this machine's own"; return; }
  remote_at="$(read_kv at "$state")"
  local_at="$(local_state_at)"
  if [[ -n "$local_at" ]] && (( local_at >= remote_at )); then
    log "this machine already has the latest state"
    return
  fi
  log "fetching state handed over by $(read_kv host "$state") $(ago "$remote_at")"
  for v in "${volumes[@]}"; do
    dk volume create "${project}_$v" >/dev/null
    # shellcheck disable=SC2016
    r2 -v "${project}_$v:/data" -e V="$v" -- \
      'find /data -mindepth 1 -maxdepth 1 -exec rm -rf {} + && rclone cat "'"$remote"'/$V.tgz" | tar xzf - -C /data'
  done
}

upload_state() {
  local now
  now="$(date +%s)"
  dk run --rm -v "${project}_jenkins_home:/data" --entrypoint sh "$rclone_image" \
    -c "printf 'at=%s\nhost=%s\n' '$now' '$host_id' > /data/.quantsim-state"
  for v in "${volumes[@]}"; do
    log "uploading $v"
    # shellcheck disable=SC2016
    r2 -v "${project}_$v:/data:ro" -e V="$v" -- \
      'tar czf - -C /data --exclude=./workspace --exclude=./caches --exclude=./.buildx \
         --exclude=./remoting --exclude=./plugins --exclude=./war --exclude=./.cache . \
       | rclone rcat "'"$remote"'/$V.tgz"'
  done
  printf 'host=%s\nat=%s\n' "$host_id" "$now" | r2 -- "rclone rcat $remote/state.env"
}

redeploy_environments() {
  local password url jar crumb job
  password="$(tr -d '\r\n' < "$secrets/admin_password")"
  local port="${JENKINS_PORT:-$(env_value JENKINS_PORT)}"
  url="http://localhost:${port:-8080}"
  mkdir -p "$here/.state"
  jar="$here/.state/cookies"
  for _ in $(seq 1 60); do
    curl -fs -o /dev/null -u "admin:$password" "$url/api/json" && break
    sleep 5
  done
  crumb="$(curl -fs -c "$jar" -u "admin:$password" "$url/crumbIssuer/api/xml?xpath=concat(//crumbRequestField,%22:%22,//crumb)" || true)"
  for job in develop test; do
    if curl -fs -o /dev/null -b "$jar" -u "admin:$password" "$url/job/quantsim/job/$job/api/json"; then
      curl -fs -o /dev/null -b "$jar" -u "admin:$password" -H "$crumb" -X POST "$url/job/quantsim/job/$job/build" \
        && log "rebuilding $job to bring its environment up on this machine"
    fi
  done
  rm -f "$jar"
}

start() {
  local force=${1:-} lease owner seen url
  lease="$(lease_text)"
  owner="$(read_kv host "$lease")"; seen="$(read_kv at "$lease")"
  if [[ -n "$owner" && "$owner" != "$host_id" ]] && (( $(date +%s) - seen < fresh_seconds )); then
    [[ "$force" == "--force" ]] \
      || die "$owner is hosting Jenkins (seen $(ago "$seen")). Ask them to run host.sh stop, or use --force if that machine is off."
    log "taking over from $owner by force"
  fi

  if ! jenkins_running; then
    restore_state
  fi

  log "starting the tunnel"
  "${compose[@]}" up -d tunnel >/dev/null
  url=""
  for _ in $(seq 1 30); do
    url="$(dk run --rm --network "${project}_default" --entrypoint sh "$rclone_image" \
      -c 'wget -qO- http://tunnel:2000/quicktunnel 2>/dev/null' \
      | sed -n 's/.*"hostname":"\([^"]*\)".*/https:\/\/\1\//p' || true)"
    [[ -n "$url" ]] && break
    sleep 2
  done
  [[ -n "$url" ]] || url="http://localhost:8080/"
  # Build links posted to GitHub point at this host's public address
  sed -i.bak "s#^JENKINS_URL=.*#JENKINS_URL=$url#" "$here/.env" && rm -f "$here/.env.bak"

  log "starting Jenkins"
  "${compose[@]}" up -d --build
  printf 'host=%s\nat=%s\nurl=%s\n' "$host_id" "$(date +%s)" "$url" | r2 -- "rclone rcat $remote/lease.env"

  redeploy_environments
  log "Jenkins is hosted here: $url (sign in as admin)"
}

stop() {
  local lease owner seen
  lease="$(lease_text)"
  owner="$(read_kv host "$lease")"; seen="$(read_kv at "$lease")"

  log "stopping Jenkins"
  "${compose[@]}" down

  if [[ -n "$owner" && "$owner" != "$host_id" ]] && (( $(date +%s) - seen < fresh_seconds )); then
    log "$owner took over in the meantime; keeping their state and not uploading this machine's"
    return
  fi
  upload_state
  r2 -- "rclone deletefile $remote/lease.env 2>/dev/null || true"
  log "Jenkins state handed over; anyone can now run: ci/jenkins/host.sh start"
}

case "${1:-}" in
  status) status ;;
  start)  start "${2:-}" ;;
  stop)   stop ;;
  *)      sed -n '2,15p' "$0"; exit 1 ;;
esac
