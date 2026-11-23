#!/usr/bin/env bash
# Installs the tunnel watchdog (tunnel-watchdog.sh) as a systemd timer on the machine that
# hosts Jenkins with host.sh. It runs 2 minutes after boot and then every 3 minutes, as the
# account that ran this installer (which owns the clone and can use Docker). Run once, as
# root, from the clone the watchdog should run from; running it again only rewrites what
# changed:
#
#   sudo ci/jenkins/install-tunnel-watchdog.sh
#
# It also makes sure Docker starts at boot, so the environments, Jenkins and the tunnels
# (all restart: unless-stopped) come back by themselves after a reboot or power cut; the
# watchdog then publishes their new addresses. Watch it with:
#
#   journalctl -u quantsim-tunnel-watchdog -f
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run as root: sudo $0" >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd is required" >&2; exit 1; }

here="$(cd "$(dirname "$0")" && pwd)"
user="${SUDO_USER:-}"
[[ -n "$user" && "$user" != root ]] \
  || { echo "run it with sudo from the account that hosts Jenkins, not as root itself" >&2; exit 1; }
id -nG "$user" | tr ' ' '\n' | grep -qx docker \
  || { echo "$user must be in the docker group (sudo usermod -aG docker $user, then log in again)" >&2; exit 1; }
[[ -x "$here/tunnel-watchdog.sh" ]] || { echo "$here/tunnel-watchdog.sh must be executable" >&2; exit 1; }

unit=/etc/systemd/system/quantsim-tunnel-watchdog
changed=0
write() { # write <path>: replaces the file with stdin only when the content differs
  local tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  if [[ -f "$1" ]] && cmp -s "$tmp" "$1"; then
    rm -f "$tmp"
  else
    install -m 644 "$tmp" "$1" && rm -f "$tmp"
    echo "wrote $1"
    changed=1
  fi
}

write "$unit.service" <<EOF
[Unit]
Description=QuantSim tunnel watchdog (keeps the public addresses of DEV, TEST, ACC, PROD and Jenkins working)
Documentation=file://$here/README.md
Wants=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
User=$user
WorkingDirectory=$here
ExecStart="$here/tunnel-watchdog.sh"
TimeoutStartSec=15min
Nice=5
EOF

write "$unit.timer" <<'EOF'
[Unit]
Description=Run the QuantSim tunnel watchdog every 3 minutes

[Timer]
OnBootSec=2min
OnUnitInactiveSec=3min
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF

if (( changed )); then systemctl daemon-reload; fi
systemctl enable docker.service >/dev/null 2>&1 || true
systemctl enable --now quantsim-tunnel-watchdog.timer >/dev/null
echo "installed; next run:"
systemctl list-timers quantsim-tunnel-watchdog.timer --no-pager
