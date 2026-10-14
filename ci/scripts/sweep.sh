#!/usr/bin/env bash
# Frees the Docker disk space builds leave behind, so the Jenkins host never fills up.
# Runs after every build; safe to run by hand at any time.
#   usage: sweep.sh
#
# - test containers (qs-ci-*) that have stopped, with their volumes, and their networks.
#   A build cleans these up itself, but not when Docker or the agent dies mid-build.
#   Containers of a build that is still running are never touched.
# - anonymous volumes no container uses any more: test databases of builds whose
#   scripts removed the container without its volume (older branches still do)
# - dangling images (old layers no tag points at any more)
# - build cache beyond SWEEP_KEEP_CACHE (default 3gb), oldest first, in Docker's own
#   cache and in the qs-builder cache that image builds use
source "$(dirname "$0")/lib.sh"

keep_cache="${SWEEP_KEEP_CACHE:-3gb}"

mapfile -t stopped < <(docker ps -aq --filter 'name=^qs-ci-' --filter status=exited --filter status=created --filter status=dead)
if (( ${#stopped[@]} )); then
  docker rm -fv "${stopped[@]}" >/dev/null
  log "removed ${#stopped[@]} leftover test container(s)"
fi

mapfile -t networks < <(docker network ls -q --filter 'name=^qs-ci-')
for network in "${networks[@]}"; do
  # A network still in use by a running build refuses removal; that is expected
  docker network rm "$network" >/dev/null 2>&1 || true
done

# Only anonymous volumes; named volumes (DEV, TEST, Jenkins) are never touched
docker volume prune -f >/dev/null
docker image prune -f >/dev/null
docker builder prune -f --max-used-space "$keep_cache" >/dev/null
# Known only to builds that created it in this workspace (DOCKER_CONFIG)
docker buildx prune --builder qs-builder -f --max-used-space "$keep_cache" >/dev/null 2>&1 || true
log "Docker sweep done (build cache kept under $keep_cache)"
