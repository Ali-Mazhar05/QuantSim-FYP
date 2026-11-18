#!/usr/bin/env bash
# Generates a new QuantSim backend service from scripts/service-template (K2).
#
#   usage: scripts/new-service.sh <name> [--no-secrets]
#     <name>  lowercase letters and digits, e.g. simulation; the package is qs_<name>,
#             the API lives under /api/<name>, the database and role are both <name>
#
# It creates services/<name> (API with /health, job worker, outbox relay, Alembic with a
# first migration for the job, outbox and processed_events tables, tests), and wires it
# in: ci/components.conf, the compose services and Traefik route, db-init (database,
# role, TimescaleDB), the workspace lockfile and, unless --no-secrets, a random
# <NAME>_DB_PASSWORD in every environment's encrypted secrets (needs the age key, see
# ci/scripts/set-secret.sh). Commit everything it changed through a pull request.
set -euo pipefail

name="${1:?usage: scripts/new-service.sh <name> [--no-secrets]}"
secrets=1
[[ "${2:-}" == "--no-secrets" ]] && secrets=0

die() { echo "new-service: $*" >&2; exit 1; }
[[ "$name" =~ ^[a-z][a-z0-9]*$ ]] || die "the name must be lowercase letters and digits, e.g. simulation"

root="$(git rev-parse --show-toplevel)"
cd "$root"
template="scripts/service-template"
target="services/$name"
compose="deploy/compose/docker-compose.yml"
components="ci/components.conf"
[[ -d "$template" ]] || die "no template at $template"
[[ ! -e "$target" ]] || die "$target already exists"

pkg="qs_$name"
dist="qs-$name"
upper="$(tr '[:lower:]' '[:upper:]' <<<"$name")"
title="${upper:0:1}${name:1}"

render() {
  sed -e "s/__pkg__/$pkg/g" -e "s/__dist__/$dist/g" -e "s/__Title__/$title/g" \
      -e "s/__Class__/$title/g" -e "s/__NAME__/$upper/g" -e "s/__name__/$name/g"
}

# 1. The service folder: copy every template file, renaming and filling placeholders
while IFS= read -r -d '' file; do
  relative="${file#"$template"/}"
  [[ "$relative" == compose.part.yml ]] && continue
  out="$target/$(render <<<"$relative")"
  mkdir -p "$(dirname "$out")"
  render < "$file" > "$out"
done < <(find "$template" -type f -print0)
echo "created $target"

# 2. ci/components.conf: one image per service, rebuilt when its paths change
grep -qE "^$name[[:space:]]" "$components" \
  || printf '%-12s service  %s/Dockerfile  .  %s libs/qs_template pyproject.toml uv.lock\n' \
       "$name" "$target" "$target" >> "$components"
echo "added $name to $components"

# 3. Compose: the service block, its db-init password and its database
insert_before() {  # insert_before <marker> <text-file>
  local marker=$1 text=$2 tmp
  grep -qF "$marker" "$compose" || die "marker not found in $compose: $marker"
  tmp="$(mktemp)"
  awk -v marker="$marker" -v file="$text" '
    index($0, marker) { while ((getline line < file) > 0) print line; close(file) }
    { print }' "$compose" > "$tmp"
  mv "$tmp" "$compose"
}
part="$(mktemp)"
trap 'rm -f "$part"' EXIT
render < "$template/compose.part.yml" > "$part"
insert_before "# new-service.sh: generated services go above this line" "$part"

printf '      %s_DB_PASSWORD: ${%s_DB_PASSWORD:?%s_DB_PASSWORD comes from the environment'"'"'s secrets}\n' \
  "$upper" "$upper" "$upper" > "$part"
insert_before "# new-service.sh: generated database passwords go above this line" "$part"

cat > "$part" <<EOF
        create $name "\$\$${upper}_DB_PASSWORD"
        PGDATABASE=$name psql -v ON_ERROR_STOP=1 -q -c 'CREATE EXTENSION IF NOT EXISTS timescaledb'
        echo "extension ready: timescaledb in $name"
EOF
insert_before "# new-service.sh: generated databases go above this line" "$part"
echo "wired $name into $compose (API, worker, relay, migrate, Traefik /api/$name, db-init)"

# 4. The workspace lockfile picks up the new project; imports are sorted for this name
#    (qs_<name> sorts before or after qs_template depending on the name)
if command -v uv >/dev/null; then
  uv lock --quiet && echo "updated uv.lock"
  (cd "$target" && uvx --quiet ruff check --fix --select I . && uvx --quiet ruff format .) \
    && echo "sorted imports and formatted $target"
else
  echo "uv not found: run 'uv lock' and 'ruff check --fix && ruff format' in $target before committing"
fi

# 5. A database password in every environment's encrypted secrets
if (( secrets )); then
  for env in dev test acc prod; do
    # read (in set-secret.sh) needs the closing newline
    { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; echo; } \
      | ci/scripts/set-secret.sh "${upper}_DB_PASSWORD" "$env" >/dev/null
    echo "stored ${upper}_DB_PASSWORD for $env"
  done
else
  echo "skipped secrets: run 'ci/scripts/set-secret.sh ${upper}_DB_PASSWORD <env>' for dev, test, acc and prod"
fi

echo "next: ci/scripts/python-ci.sh $target && ci/scripts/migration-check.sh $name, then open a pull request"
