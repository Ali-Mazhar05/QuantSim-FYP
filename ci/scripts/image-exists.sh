#!/usr/bin/env bash
# Checks whether an image tag exists.
#   usage: image-exists.sh <image:tag>
#   exit 0  the image exists
#   exit 1  the image does not exist
#   exit 3  the registry refused access (also what GHCR answers for a package
#           that has never been pushed)
#   exit 2  any other failure, such as a network error; never treated as "missing"
source "$(dirname "$0")/lib.sh"

ref="${1:?usage: image-exists.sh <image:tag>}"

if [[ "$QS_LOCAL" == "1" ]]; then
  docker image inspect "$ref" >/dev/null 2>&1 && exit 0
  exit 1
fi

if err="$(docker buildx imagetools inspect "$ref" 2>&1 >/dev/null)"; then
  exit 0
fi

if grep -qiE 'not found|manifest unknown|name unknown|404' <<<"$err"; then
  exit 1
fi
if grep -qiE 'denied|unauthorized|403|401' <<<"$err"; then
  log "registry refused access to $ref: $err"
  exit 3
fi

log "could not check $ref: $err"
exit 2
