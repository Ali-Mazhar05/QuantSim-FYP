#!/usr/bin/env bash
# Lints, type checks, tests and builds the frontend in a pinned Node container.
# Test results land in frontend/reports/junit.xml and coverage in frontend/coverage.
#   usage: frontend-ci.sh
source "$(dirname "$0")/lib.sh"

# The command runs inside the container, so its variables must not expand here
# shellcheck disable=SC2016
run_in_image "$NODE_IMAGE" -e CI=true -- sh -ec '
  cd frontend
  npm ci --no-audit --no-fund --cache "${npm_config_cache:-../.ci/npm-cache}"
  echo "--- lint";      npm run lint
  echo "--- typecheck"; npm run typecheck
  echo "--- test";      npm run test:ci
  echo "--- build";     npm run build
'
