#!/usr/bin/env bash
# Maps a branch to the environment it deploys to and what the pipeline does with it.
#   usage: env-for-branch.sh <branch>
#   prints: <env> <mode>
#     env   dev | test | acc | prod | none
#     mode  build   (build missing images)
#           promote (reuse images built on develop)
#           ci      (checks only)
set -euo pipefail

branch="${1:?usage: env-for-branch.sh <branch>}"

case "$branch" in
  develop)    echo "dev build" ;;
  test)       echo "test promote" ;;
  acceptance) echo "acc promote" ;;
  main)       echo "prod promote" ;;
  hotfix/*)   echo "none build" ;;
  *)          echo "none ci" ;;
esac
