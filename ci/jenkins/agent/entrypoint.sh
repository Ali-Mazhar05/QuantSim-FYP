#!/usr/bin/env bash
# Builds reach Docker through the host's socket. SSH sessions take their groups from
# /etc/group, not from the container's group_add, so give the jenkins user the
# socket's group before starting sshd. The socket's group differs per host
# (0 on Docker Desktop, the docker group on Linux).
set -euo pipefail

socket=/var/run/docker.sock
if [[ -S "$socket" ]]; then
  gid="$(stat -c %g "$socket")"
  group="$(getent group "$gid" | cut -d: -f1 || true)"
  if [[ -z "$group" ]]; then
    group=docker-host
    groupadd --gid "$gid" "$group"
  fi
  usermod -aG "$group" jenkins
fi

# The work directory is a volume; make sure the jenkins user owns it
chown jenkins:jenkins /home/jenkins/agent

exec setup-sshd "$@"
