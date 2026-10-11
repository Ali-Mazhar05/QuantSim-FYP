#!/usr/bin/env bash
# Points a tag such as test, acc, prod or v0.1.0 at the image already built for the
# component's current content hash. Nothing is rebuilt and nothing is downloaded.
#   usage: promote.sh <component> <tag>
source "$(dirname "$0")/lib.sh"

name="${1:?usage: promote.sh <component> <tag>}"
tag="${2:?usage: promote.sh <component> <tag>}"

hash="$("$(dirname "$0")/content-hash.sh" "$name")"
repo="$(image_repo "$name")"

status=0
"$(dirname "$0")/image-exists.sh" "$repo:$hash" || status=$?
case "$status" in
  0) ;;
  1|3) die "$repo:$hash was never built. Merge the change into develop first so it is built and verified there." ;;
  *) die "could not reach the registry to check $repo:$hash" ;;
esac

if [[ "$QS_LOCAL" == "1" ]]; then
  docker tag "$repo:$hash" "$repo:$tag"
else
  docker buildx imagetools create --tag "$repo:$tag" "$repo:$hash"
fi

log "promoted $repo:$hash to $repo:$tag"
