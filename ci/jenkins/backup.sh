#!/usr/bin/env bash
# Backs up Jenkins (jobs, history, configuration) and the build agent (recorded
# releases) to compressed archives, keeping the last 14 of each. Installed as a
# nightly cron job by bootstrap-server.sh; safe to run by hand at any time.
#
# Optional off-site copy to Cloudflare R2 (free up to 10 GB): put these in
# /etc/quantsim-backup.env and they are uploaded after every backup:
#   R2_ACCOUNT_ID=...  R2_ACCESS_KEY_ID=...  R2_SECRET_ACCESS_KEY=...  R2_BUCKET=...
#
# Restore one volume (with Jenkins stopped):
#   docker run --rm -v quantsim-jenkins_jenkins_home:/data -v /var/backups/quantsim:/backup \
#     alpine sh -c 'rm -rf /data/* && tar xzf /backup/<file>.tgz -C /data'
set -euo pipefail

dest="${BACKUP_DIR:-/var/backups/quantsim}"
keep=14
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
alpine="alpine:3.22@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8"
rclone="rclone/rclone:1.71@sha256:3103526c506266a9ecdf064efe99bf3677d92ef6407af124d8c56b4f49cbaa51"

mkdir -p "$dest"

for volume in quantsim-jenkins_jenkins_home quantsim-jenkins_agent_home; do
  docker volume inspect "$volume" >/dev/null 2>&1 || { echo "skipping missing volume $volume"; continue; }
  archive="$volume-$stamp.tgz"
  # Workspaces, caches, plugins and the unpacked web app come back from the image or
  # the next build; leave them out
  docker run --rm -v "$volume":/data:ro -v "$dest":/backup "$alpine" \
    tar czf "/backup/$archive" -C /data \
      --exclude=./workspace --exclude=./caches --exclude=./.buildx --exclude=./remoting \
      --exclude=./plugins --exclude=./war --exclude=./.cache .
  echo "$(date -u +%FT%TZ) wrote $dest/$archive ($(du -h "$dest/$archive" | cut -f1))"
  # Archive names sort by time, so everything but the newest $keep goes
  find "$dest" -maxdepth 1 -name "$volume-*.tgz" | sort -r | tail -n +$((keep + 1)) | xargs -r rm -f
done

if [[ -f /etc/quantsim-backup.env ]]; then
  # shellcheck disable=SC1091
  source /etc/quantsim-backup.env
  docker run --rm -v "$dest":/backup:ro \
    -e RCLONE_CONFIG_R2_TYPE=s3 -e RCLONE_CONFIG_R2_PROVIDER=Cloudflare \
    -e RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
    -e RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
    -e RCLONE_CONFIG_R2_ENDPOINT="https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com" \
    "$rclone" copy /backup "r2:$R2_BUCKET/jenkins" --max-age 48h
  echo "$(date -u +%FT%TZ) uploaded to R2 bucket $R2_BUCKET"
fi
