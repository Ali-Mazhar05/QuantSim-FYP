#!/usr/bin/env bash
# Prints the content hash of a component: a short digest of the git object ids of
# the paths listed for it in ci/components.conf. Identical content gives an
# identical hash on any branch, so a promotion merge never forces a rebuild.
# Uncommitted changes are not part of the hash.
#   usage: content-hash.sh <component>
source "$(dirname "$0")/lib.sh"

name="${1:?usage: content-hash.sh <component>}"

mapfile -t paths < <(component_paths "$name")
(( ${#paths[@]} )) || die "component $name lists no paths"

{
  printf 'component %s\n' "$name"
  for path in "${paths[@]}"; do
    id="$(git -C "$REPO_ROOT" rev-parse --verify --quiet "HEAD:$path")" \
      || die "path '$path' of component $name does not exist in HEAD"
    printf '%s %s\n' "$path" "$id"
  done
} | sha256sum | cut -c1-12
