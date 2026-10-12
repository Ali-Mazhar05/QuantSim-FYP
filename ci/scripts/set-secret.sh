#!/usr/bin/env bash
# Stores one secret in the encrypted secrets of one or more environments. The value is
# typed (or pasted) without being shown, and never written anywhere unencrypted.
#   usage: ci/scripts/set-secret.sh <NAME> <env>...    env: dev, test, acc, prod or all
#   e.g.   ci/scripts/set-secret.sh SMTP_PASSWORD all
#   needs: an age key listed in .sops.yaml, in SOPS_AGE_KEY_FILE or at
#          ci/jenkins/secrets/sops_age_key
# Commit the changed deploy/secrets/*.enc.env files through a pull request; the next
# deploy of each environment uses the new value.
source "$(dirname "$0")/lib.sh"

name="${1:?usage: set-secret.sh <NAME> <env>... (dev, test, acc, prod or all)}"
shift
(( $# )) || die "name at least one environment (dev, test, acc, prod or all)"
[[ "$name" =~ ^[A-Z][A-Z0-9_]*$ ]] || die "the name must look like SMTP_PASSWORD"

envs=()
for env in "$@"; do
  if [[ "$env" == "all" ]]; then
    envs+=(dev test acc prod)
  else
    [[ -f "$REPO_ROOT/deploy/secrets/$env.enc.env" ]] || die "no secrets file for $env"
    envs+=("$env")
  fi
done

key_file="${SOPS_AGE_KEY_FILE:-$REPO_ROOT/ci/jenkins/secrets/sops_age_key}"
[[ -s "$key_file" ]] || die "no age key at $key_file; set SOPS_AGE_KEY_FILE"

read -rsp "Value for $name: " value
printf '\n'
[[ -n "$value" ]] || die "empty value; nothing changed"
# Gmail shows app passwords in groups of four; the spaces are not part of it
[[ "$name" == "SMTP_PASSWORD" ]] && value="${value// /}"
quoted="${value//\\/\\\\}"
quoted="\"${quoted//\"/\\\"}\""

for env in "${envs[@]}"; do
  SOPS_AGE_KEY="$(cat "$key_file")" run_in_image "$SOPS_IMAGE" -e SOPS_AGE_KEY -- \
    set "deploy/secrets/$env.enc.env" "[\"$name\"]" "$quoted" \
    || die "could not update the secrets of $env"
  log "$name set for $env"
done
