#!/usr/bin/env bash
# Prepares a machine to host QuantSim Jenkins: creates the controller-to-agent SSH key,
# writes ci/jenkins/.env and checks that every secret file is present.
#
#   laptop host:  ci/jenkins/init-env.sh
#   CI server:    ci/jenkins/init-env.sh --server --domain quantsim-ci.duckdns.org \
#                   --email you@example.com --approvers "Ali-Mazhar05,teammate"
#
# Re-running it rewrites .env and keeps an existing SSH key.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
secrets="$here/secrets"

mode=laptop
domain=""
email=""
approvers=""

while (( $# )); do
  case "$1" in
    --server)    mode=server ;;
    --domain)    domain="${2:?}"; shift ;;
    --email)     email="${2:?}"; shift ;;
    --approvers) approvers="${2:?}"; shift ;;
    -h|--help)   sed -n '2,10p' "$0"; exit 0 ;;
    *)           echo "unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

if [[ "$mode" == "server" ]]; then
  [[ -n "$domain" && -n "$email" && -n "$approvers" ]] \
    || { echo "--server needs --domain, --email and --approvers" >&2; exit 1; }
fi

mkdir -p "$secrets"
if [[ ! -f "$secrets/agent_ssh_key" ]]; then
  ssh-keygen -q -t ed25519 -N "" -C "quantsim-jenkins-agent" -f "$secrets/agent_ssh_key"
  echo "created the controller-to-agent SSH key"
fi
pubkey="$(cat "$secrets/agent_ssh_key.pub")"
# Names this machine in the shared host lease (host.sh status)
host_id="${USER:-${USERNAME:-user}}@$(hostname)"

if [[ "$mode" == "server" ]]; then
  cat > "$here/.env" <<EOF
# Written by init-env.sh --server. Re-run it to change these values.
COMPOSE_FILE=compose.yml:compose.server.yml
HOST_ID=$host_id
AGENT_SSH_PUBKEY=$pubkey
JENKINS_AUTH=github
JENKINS_BIND=127.0.0.1
JENKINS_URL=https://ci.$domain/
QS_RELEASE_APPROVERS=$approvers
QS_PLATFORMS=linux/arm64,linux/amd64
QS_SCAN_INTERVAL=5m
CI_HOST=ci.$domain
DEV_HOST=dev.$domain
TEST_HOST=test.$domain
ACME_EMAIL=$email
EOF
else
  cat > "$here/.env" <<EOF
# Written by init-env.sh (laptop host). Re-run it to change these values.
HOST_ID=$host_id
AGENT_SSH_PUBKEY=$pubkey
JENKINS_AUTH=local
JENKINS_BIND=0.0.0.0
JENKINS_URL=http://localhost:8080/
QS_RELEASE_APPROVERS=admin
QS_PLATFORMS=linux/amd64
QS_SCAN_INTERVAL=2m
EOF
fi
echo "wrote ci/jenkins/.env for a $mode host"

required=(admin_password agent_ssh_key github_app_id github_app_key ghcr_user ghcr_token
          cloudflare_api_token cloudflare_account_id sops_age_key)
[[ "$mode" == "server" ]] && required+=(github_oauth_client_id github_oauth_client_secret)

missing=()
for name in "${required[@]}"; do
  [[ -s "$secrets/$name" ]] || missing+=("$name")
done
if (( ${#missing[@]} )); then
  echo "missing secret files in ci/jenkins/secrets: ${missing[*]} (see secrets/README.md)" >&2
  exit 1
fi
echo "all secret files present; start with: docker compose -f ci/jenkins/compose.yml up -d --build"
