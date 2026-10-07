#!/usr/bin/env bash
# Builds a component image tagged with its content hash and pushes it.
#   usage: build-push.sh <component>
#
#   PLATFORMS  target platforms, default linux/amd64; add linux/arm64 once an
#              environment runs on an ARM server
#   QS_LOCAL=1 build into the local Docker daemon instead of pushing
source "$(dirname "$0")/lib.sh"

name="${1:?usage: build-push.sh <component>}"
platforms="${PLATFORMS:-linux/amd64}"

hash="$("$(dirname "$0")/content-hash.sh" "$name")"
repo="$(image_repo "$name")"
dockerfile="$REPO_ROOT/$(component_field "$name" 3)"
context="$REPO_ROOT/$(component_field "$name" 4)"

build_args=(
  --build-arg "VERSION=$(project_version)"
  --build-arg "CONTENT_HASH=$hash"
  --build-arg "GIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)"
  --build-arg "BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
)

log "building $repo:$hash for $platforms"

if [[ "$QS_LOCAL" == "1" ]]; then
  docker build "${build_args[@]}" -f "$dockerfile" -t "$repo:$hash" "$context"
  exit 0
fi

# A docker-container builder is needed for multi-platform builds and registry caching
builder="qs-builder"
docker buildx inspect "$builder" >/dev/null 2>&1 \
  || docker buildx create --name "$builder" --driver docker-container >/dev/null

docker buildx build \
  --builder "$builder" \
  --platform "$platforms" \
  "${build_args[@]}" \
  --cache-from "type=registry,ref=$repo:buildcache" \
  --cache-to "type=registry,ref=$repo:buildcache,mode=max" \
  --provenance=mode=max \
  --sbom=true \
  -f "$dockerfile" \
  -t "$repo:$hash" \
  --push \
  "$context"

log "pushed $repo:$hash"
