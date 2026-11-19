#!/usr/bin/env bash
# Turns a fresh Ubuntu 24.04 server (Oracle Cloud Always Free Ampere A1, or any other)
# into the QuantSim CI server. Run once, as root, from a clone of the repository:
#
#   sudo ci/jenkins/bootstrap-server.sh
#
# It installs Docker, opens ports 80 and 443, adds swap, enables automatic security
# updates, enables building amd64 images on an ARM host, and installs the nightly
# Jenkins backup. It does not start Jenkins; see docs/ci-cd.md for the next steps.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run as root: sudo $0" >&2; exit 1; }

repo="$(cd "$(dirname "$0")/../.." && pwd)"
owner="${SUDO_USER:-ubuntu}"

log() { printf '\n== %s\n' "$*"; }

log "system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq ca-certificates curl gnupg git jq unattended-upgrades iptables-persistent

log "Docker Engine"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
usermod -aG docker "$owner"
# Cap container logs so the disk never fills with them
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
systemctl restart docker

log "firewall: allow HTTP and HTTPS"
# Oracle's Ubuntu images ship iptables rules that reject everything but SSH. The
# cloud security list must also allow 80 and 443 (see docs/ci-cd.md).
for port in 80 443; do
  iptables -C INPUT -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null \
    || iptables -I INPUT -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT
done
iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT -p udp --dport 443 -j ACCEPT
netfilter-persistent save

log "swap"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 4G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

log "automatic security updates"
dpkg-reconfigure -f noninteractive unattended-upgrades

log "multi-platform builds"
# Lets an ARM server also build linux/amd64 images (and the reverse)
docker run --privileged --rm tonistiigi/binfmt:latest@sha256:400a4873b838d1b89194d982c45e5fb3cda4593fbfd7e08a02e76b03b21166f0 --install all
# Survive reboots
cat > /etc/systemd/system/quantsim-binfmt.service <<EOF
[Unit]
Description=Register QEMU emulators for multi-platform Docker builds
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker run --privileged --rm tonistiigi/binfmt:latest@sha256:400a4873b838d1b89194d982c45e5fb3cda4593fbfd7e08a02e76b03b21166f0 --install all

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable quantsim-binfmt.service

log "nightly Jenkins backup"
cat > /etc/cron.d/quantsim-jenkins-backup <<EOF
# Nightly backup of Jenkins and the build agent (releases), see ci/jenkins/backup.sh
30 2 * * * root $repo/ci/jenkins/backup.sh >> /var/log/quantsim-jenkins-backup.log 2>&1
EOF

chown -R "$owner":"$owner" "$repo"

log "done"
cat <<EOF
Next steps (as $owner; log out and back in first so the docker group applies):
  1. Copy the secret files into $repo/ci/jenkins/secrets/ (see secrets/README.md)
  2. $repo/ci/jenkins/init-env.sh --server --domain <your-name>.duckdns.org \\
       --email <you@example.com> --approvers "<github-user>,<github-user>"
  3. docker compose -f $repo/ci/jenkins/compose.yml up -d --build
EOF
