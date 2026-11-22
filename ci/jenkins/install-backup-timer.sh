#!/usr/bin/env bash
# Installs the nightly QuantSim backup (backup.sh: Jenkins state plus the ACC and PROD
# databases) as a systemd timer on a machine that hosts Jenkins with host.sh. The CI
# server gets a cron job from bootstrap-server.sh instead. Run once, as root, from the
# clone the backup should run from; running it again only rewrites what changed:
#
#   sudo ci/jenkins/install-backup-timer.sh
#
# The timer fires at 03:30 local time; if the machine was off then, it runs shortly
# after the next boot. Output is appended to /var/log/quantsim-backup.log.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run as root: sudo $0" >&2; exit 1; }

here="$(cd "$(dirname "$0")" && pwd)"
unit=/etc/systemd/system/quantsim-backup
log_file=/var/log/quantsim-backup.log

[[ -x "$here/backup.sh" && -x "$here/backup-databases.sh" ]] \
  || { echo "backup.sh and backup-databases.sh in $here must be executable" >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd is required" >&2; exit 1; }

changed=0
# write <path>: replaces the file with stdin only when the content differs
write() {
  local tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  if [[ -f "$1" ]] && cmp -s "$tmp" "$1"; then
    rm -f "$tmp"
  else
    install -m 0644 "$tmp" "$1"
    rm -f "$tmp"
    echo "wrote $1"
    changed=1
  fi
}

write "$unit.service" <<EOF
[Unit]
Description=QuantSim nightly backup (Jenkins state, ACC and PROD databases)
Documentation=file://$here/README.md
Wants=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
ExecStart="$here/backup.sh"
StandardOutput=append:$log_file
StandardError=append:$log_file
TimeoutStartSec=2h
Nice=10
IOSchedulingClass=idle
EOF

write "$unit.timer" <<'EOF'
[Unit]
Description=Run the QuantSim backup nightly

[Timer]
OnCalendar=*-*-* 03:30:00
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
EOF

if [[ -d /etc/logrotate.d ]]; then
  write /etc/logrotate.d/quantsim-backup <<EOF
$log_file {
  monthly
  rotate 6
  compress
  missingok
  notifempty
}
EOF
fi

# The CI server's cron job runs the same script; never run both on one machine
if [[ -f /etc/cron.d/quantsim-jenkins-backup ]]; then
  rm -f /etc/cron.d/quantsim-jenkins-backup
  echo "removed /etc/cron.d/quantsim-jenkins-backup (replaced by the timer)"
fi

if (( changed )); then systemctl daemon-reload; fi
systemctl enable --now quantsim-backup.timer >/dev/null
touch "$log_file"

[[ -f /etc/quantsim-backup.env ]] \
  || echo "note: /etc/quantsim-backup.env is missing, so backups stay on this machine only (see ci/jenkins/README.md)"
echo "installed; next run:"
systemctl list-timers quantsim-backup.timer --no-pager
