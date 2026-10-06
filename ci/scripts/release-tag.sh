#!/usr/bin/env bash
# Tags a production release with the version in the VERSION file.
#   usage: release-tag.sh check    fail early if VERSION is invalid or already released
#          release-tag.sh create   create and push the annotated tag v<VERSION> on HEAD
#   needs: GITHUB_TOKEN, GITHUB_REPO
source "$(dirname "$0")/lib.sh"

action="${1:?usage: release-tag.sh check|create}"
require_env GITHUB_TOKEN GITHUB_REPO

version="$(project_version)"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION must look like 1.2.3, found '$version'"
tag="v$version"
remote="https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPO}.git"

status=0
git -C "$REPO_ROOT" ls-remote --exit-code --tags "$remote" "refs/tags/$tag" >/dev/null 2>&1 || status=$?
case "$status" in
  0) die "$tag is already released. Bump the VERSION file in develop and promote it again." ;;
  2) ;;
  *) die "could not read tags from GitHub (git exit code $status)" ;;
esac

case "$action" in
  check)
    log "$tag is free to release"
    ;;
  create)
    git -C "$REPO_ROOT" \
      -c user.name="quantsim-jenkins" -c user.email="jenkins@quantsim.invalid" \
      tag -a "$tag" -m "Release $tag" HEAD
    git -C "$REPO_ROOT" push --quiet "$remote" "refs/tags/$tag"
    log "released $tag at $(git -C "$REPO_ROOT" rev-parse --short HEAD)"
    ;;
  *)
    die "unknown action: $action"
    ;;
esac
