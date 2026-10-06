#!/usr/bin/env bash
# Publishes the frontend of a release to Cloudflare Pages. The site files are copied
# out of the already-built frontend image, so Pages serves exactly the bytes that
# were tested in DEV and TEST.
#   usage: pages-deploy.sh <env> <release-file>
#   needs: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
source "$(dirname "$0")/lib.sh"

WRANGLER_VERSION="4.148.0"

env="${1:?usage: pages-deploy.sh <env> <release-file>}"
release="${2:?usage: pages-deploy.sh <env> <release-file>}"

load_env "$env"
load_release "$release"
require_env FRONTEND_IMAGE FRONTEND_HASH PAGES_PROJECT PAGES_BRANCH PAGES_PRODUCTION_BRANCH \
  CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID

site_dir=".ci/pages/$env"
rm -rf "${REPO_ROOT:?}/$site_dir"
mkdir -p "$REPO_ROOT/$site_dir"

[[ "$QS_LOCAL" == "1" ]] || docker pull --quiet "$FRONTEND_IMAGE" >/dev/null
container="$(docker create "$FRONTEND_IMAGE")"
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT
docker cp "$container:/usr/share/nginx/html/." "$REPO_ROOT/$site_dir"

grep -q "\"content_hash\":\"$FRONTEND_HASH\"" "$REPO_ROOT/$site_dir/version.json" \
  || die "the site copied from $FRONTEND_IMAGE does not carry content hash $FRONTEND_HASH"

# Create the Pages project on first use
if [[ "$(cf_pages_api GET "/$PAGES_PROJECT" | jq -r '.success')" != "true" ]]; then
  log "creating Cloudflare Pages project $PAGES_PROJECT"
  response="$(cf_pages_api POST "" "{\"name\":\"$PAGES_PROJECT\",\"production_branch\":\"$PAGES_PRODUCTION_BRANCH\"}")"
  [[ "$(jq -r '.success' <<<"$response")" == "true" ]] || die "could not create the Pages project: $response"
fi

log "publishing $FRONTEND_IMAGE to Pages project $PAGES_PROJECT, branch $PAGES_BRANCH"
run_in_image "$NODE_IMAGE" \
  -e CLOUDFLARE_API_TOKEN -e CLOUDFLARE_ACCOUNT_ID -e CI=true -e WRANGLER_SEND_METRICS=false -- \
  npx --yes "wrangler@$WRANGLER_VERSION" pages deploy "$site_dir" \
    --project-name "$PAGES_PROJECT" \
    --branch "$PAGES_BRANCH" \
    --commit-hash "$QS_RELEASE_GIT_SHA" \
    --commit-message "QuantSim $QS_RELEASE_VERSION frontend $FRONTEND_HASH" \
    --commit-dirty=true

log "published to $(pages_url)"
