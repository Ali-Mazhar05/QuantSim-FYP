#!/usr/bin/env bash
# Frees the Docker disk space builds leave behind, so the Jenkins host never fills up.
# Runs after every build; safe to run by hand at any time.
#   usage: sweep.sh
#
# - test containers (qsci-*, and qs-ci-* of older branches) that have stopped, with their volumes, and their networks.
#   A build cleans these up itself, but not when Docker or the agent dies mid-build.
#   Containers of a build that is still running are never touched, and nothing younger
#   than two hours is (SWEEP_MIN_AGE_SECONDS), so a build starting its own is left alone.
# - anonymous volumes no container uses any more: test databases of builds whose
#   scripts removed the container without its volume (older branches still do)
# - dangling images (old layers no tag points at any more)
# - build cache beyond SWEEP_KEEP_CACHE (default 3gb), oldest first, in Docker's own
#   cache and in the qs-builder cache that image builds use
source "$(dirname "$0")/lib.sh"

keep_cache="${SWEEP_KEEP_CACHE:-3gb}"

# Only what is older than this: a container another build has just created but not yet
# started is "created", and a network it has just made has no container yet; removing either
# broke that build ("test broker exited while starting", PR-172 and PR-174, once the webhook
# made builds overlap). A build cleans its own up in minutes, so older ones are leftovers.
min_age_seconds="${SWEEP_MIN_AGE_SECONDS:-7200}"
now="$(date +%s)"
old_enough() { # <docker object id> <Go template for its creation time>
  local created
  created="$(docker inspect --format "$2" "$1" 2>/dev/null)" || return 1
  # A network's time ends in a zone name ("... +0000 UTC") that date does not read
  created="$(date -d "${created% [A-Z]*}" +%s 2>/dev/null)" || return 1
  (( now - created >= min_age_seconds ))
}

# Test containers are named qsci-<build> (qs-ci- before 22 Nov, see lib.sh test_id)
mapfile -t candidates < <(docker ps -aq --filter 'name=^qsci-' --filter 'name=^qs-ci-'   --filter status=exited --filter status=created --filter status=dead)
stopped=()
for container in "${candidates[@]}"; do
  old_enough "$container" '{{.Created}}' && stopped+=("$container")
done
if (( ${#stopped[@]} )); then
  docker rm -fv "${stopped[@]}" >/dev/null
  log "removed ${#stopped[@]} leftover test container(s)"
fi

mapfile -t networks < <(docker network ls -q --filter 'name=^qsci-' --filter 'name=^qs-ci-')
for network in "${networks[@]}"; do
  old_enough "$network" '{{.Created}}' || continue
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
