#!/usr/bin/env bash
# Dumps every service database (platform, market, simulation, risk, trading and any
# added later) of the ACC and PROD stacks running on this machine, in PostgreSQL's
# custom format, and checks that each dump can be read back. Called by backup.sh; safe
# to run by hand at any time. An environment whose postgres container is not running is
# skipped. Keeps the newest 14 dumps per environment and database.
#
#   usage: backup-databases.sh [env...]        (default: acc prod)
#
# Dumps land in $BACKUP_DIR/db (default /var/backups/quantsim/db) as
# <env>-<database>-<UTC stamp>.dump. Restore steps are in ci/jenkins/README.md.
set -euo pipefail

dest="${BACKUP_DIR:-/var/backups/quantsim}/db"
keep=14
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
superuser=qs_admin
envs=("$@")
(( ${#envs[@]} )) || envs=(acc prod)

log() { echo "$(date -u +%FT%TZ) $*"; }

# Dumps hold user data, so only root may read them
umask 077
mkdir -p "$dest"
chmod 700 "$dest"

# Runs a command in the postgres container as the superuser. The password, if the
# server asks for one, is the container's own POSTGRES_PASSWORD; it is never read or
# printed on this side. Callers inside the read loop below must give it its own stdin
# (docker exec -i would otherwise swallow the rest of the database list).
# shellcheck disable=SC2016
in_postgres() {
  local container="$1"; shift
  docker exec -i "$container" sh -c 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec "$@"' sh "$@"
}

failed=0
for env in "${envs[@]}"; do
  project="qs-$env"
  container="$(docker ps -q --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=postgres" --filter status=running | head -1)"
  if [[ -z "$container" ]]; then
    log "skipping $env: no running postgres in compose project $project"
    continue
  fi

  if ! databases="$(in_postgres "$container" psql -U "$superuser" -d postgres -XAt -v ON_ERROR_STOP=1 \
      -c "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY 1" < /dev/null)"; then
    log "ERROR $env: could not list the databases"
    failed=1
    continue
  fi
  databases="$(tr -d '\r' <<<"$databases")"
  if [[ -z "$databases" ]]; then
    log "skipping $env: no service databases yet"
    continue
  fi

  while IFS= read -r db; do
    [[ -n "$db" ]] || continue
    file="$dest/$env-$db-$stamp.dump"
    # Written under a temporary name so a failed dump never looks like a good one
    # TimescaleDB's catalog makes pg_dump warn about circular foreign keys on every
    # run; those warnings are harmless for a full dump and are left out of the log
    if ! in_postgres "$container" pg_dump -U "$superuser" -d "$db" -Fc < /dev/null > "$file.partial"         2> >(grep -v -e 'circular foreign-key constraints' -e '^pg_dump: detail: ' -e '^pg_dump: hint: ' >&2); then
      log "ERROR $env/$db: pg_dump failed"
      rm -f "$file.partial"
      failed=1
      continue
    fi
    # Verify: the dump must be non-empty, its table of contents must read back, and
    # the whole archive (every data block) must decode into a restore script
    if [[ ! -s "$file.partial" ]] \
        || ! in_postgres "$container" pg_restore --list < "$file.partial" > /dev/null \
        || ! in_postgres "$container" pg_restore -f /dev/null < "$file.partial"; then
      log "ERROR $env/$db: the dump does not read back; kept as $file.partial"
      failed=1
      continue
    fi
    mv "$file.partial" "$file"
    log "wrote $file ($(du -h "$file" | cut -f1)), verified"
    # Names sort by time, so everything but the newest $keep goes
    find "$dest" -maxdepth 1 -name "$env-$db-[0-9]*.dump" | sort -r | tail -n +$((keep + 1)) | xargs -r rm -f
  done <<<"$databases"
done

# Unreadable dumps from earlier failed runs are kept a week for inspection, no longer
find "$dest" -maxdepth 1 -name '*.dump.partial' -mtime +7 -delete

exit "$failed"
