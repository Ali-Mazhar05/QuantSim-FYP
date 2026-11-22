#!/usr/bin/env bash
# Reports the free disk space on the Jenkins host (A-NFR-15): the filesystem holding
# Docker's data (images, volumes, build cache: what fills up first) and the one holding the
# build workspace. Prints a WARNING line for each below DISK_MIN_FREE_GB (default 20).
# Advisory only: it never fails the build, whatever happens, so the Prepare stage calls
# it as is. Free space by hand: ci/scripts/sweep.sh.
#   usage: disk-check.sh
source "$(dirname "$0")/lib.sh"
set +e +o pipefail

min_gb="${DISK_MIN_FREE_GB:-20}"
[[ "$min_gb" =~ ^[0-9]+$ ]] || min_gb=20

# Free GiB of the filesystem holding a path, from `df -Pk` output on stdin
free_gb_of() { awk 'NR == 2 && $4 ~ /^[0-9]+$/ { printf "%d\n", $4 / 1048576 }'; }

report() {
  local what=$1 path=$2 free=$3
  if [[ -z "$free" ]]; then
    log "disk check: could not read the free space of $what ($path)"
  elif (( free < min_gb )); then
    log "WARNING: disk check: only ${free} GB free for $what ($path), below ${min_gb} GB; run ci/scripts/sweep.sh or free space on the Jenkins host"
  else
    log "disk check: ${free} GB free for $what ($path), minimum ${min_gb} GB"
  fi
}

docker_root_free() {
  local root=$1
  # The agent may itself run in a container that does not see the host's Docker root, so
  # read it from a container that mounts it
  if [[ ! -f /.dockerenv && -d "$root" ]]; then
    df -Pk "$root" 2>/dev/null | free_gb_of
  else
    timeout 120 docker run --rm -v "$root:/docker-root:ro" --entrypoint df "$UV_IMAGE" \
      -Pk /docker-root 2>/dev/null | free_gb_of
  fi
}

root="$(timeout 30 docker info --format '{{.DockerRootDir}}' 2>/dev/null)"
if [[ -n "$root" ]]; then
  report "the Docker root" "$root" "$(docker_root_free "$root")"
else
  log "disk check: cannot reach Docker to find its data directory"
fi

workspace="${WORKSPACE:-$REPO_ROOT}"
report "the workspace" "$workspace" "$(df -Pk "$workspace" 2>/dev/null | free_gb_of)"
exit 0
