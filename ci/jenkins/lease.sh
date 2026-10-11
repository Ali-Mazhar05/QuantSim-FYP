#!/bin/sh
# Heartbeat of the shared Jenkins host lease, run by the "lease" service in compose.yml
# while this machine hosts Jenkins. Every 2 minutes it records in R2 who hosts Jenkins,
# when it was last seen and its public link, so `host.sh status` can tell anyone where
# Jenkins is and `host.sh start` can refuse to start a second Jenkins elsewhere.
set -eu

export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER="${QS_STATE_PROVIDER:-Cloudflare}"
RCLONE_CONFIG_R2_ACCESS_KEY_ID="$(cat /run/secrets/r2_access_key_id)"
RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$(cat /run/secrets/r2_secret_access_key)"
RCLONE_CONFIG_R2_ENDPOINT="${QS_STATE_ENDPOINT:-https://$(cat /run/secrets/cloudflare_account_id).r2.cloudflarestorage.com}"
# The R2 token is limited to the one bucket and may not create buckets
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true
export RCLONE_CONFIG_R2_ACCESS_KEY_ID RCLONE_CONFIG_R2_SECRET_ACCESS_KEY RCLONE_CONFIG_R2_ENDPOINT

lease="r2:${QS_STATE_BUCKET}/jenkins/lease.env"
fresh_seconds=600

while true; do
  now="$(date +%s)"
  current="$(rclone cat "$lease" 2>/dev/null || true)"
  owner="$(printf '%s\n' "$current" | sed -n 's/^host=//p')"
  seen="$(printf '%s\n' "$current" | sed -n 's/^at=//p')"

  if [ -n "$owner" ] && [ "$owner" != "$HOST_ID" ] && [ $((now - ${seen:-0})) -lt "$fresh_seconds" ]; then
    echo "WARNING: $owner holds the Jenkins host lease; stop Jenkins here with ci/jenkins/host.sh stop"
  else
    url="$(wget -qO- http://tunnel:2000/quicktunnel 2>/dev/null | sed -n 's/.*"hostname":"\([^"]*\)".*/https:\/\/\1/p' || true)"
    printf 'host=%s\nat=%s\nurl=%s\n' "$HOST_ID" "$now" "${url:-http://localhost:8080/}" | rclone rcat "$lease"
  fi

  sleep 120
done
