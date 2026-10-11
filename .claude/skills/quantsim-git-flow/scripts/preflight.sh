#!/usr/bin/env bash
# Checks that the current branch is ready to push, then runs the CI checks for exactly
# what it changed (the same scripts Jenkins runs).
#
#   preflight.sh            check and run
#   preflight.sh --plan     check, print what would run, run nothing
#   preflight.sh --base origin/develop
#
# Exit 0 means: safe to push. Anything else: fix and re-run.
set -euo pipefail
export MSYS_NO_PATHCONV=1

root="$(git rev-parse --show-toplevel)"
cd "$root"

base=""
plan_only=0
while (( $# )); do
  case "$1" in
    --plan) plan_only=1 ;;
    --base) base="${2:?}"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

fail() { echo "PREFLIGHT FAIL: $*" >&2; exit 1; }
warn() { echo "warning: $*" >&2; }
ok() { echo "ok    $*"; }

# 1. Branch -------------------------------------------------------------------------------
branch="$(git branch --show-current)"
case "$branch" in
  feature/*|bugfix/*) default_base="origin/develop" ;;
  hotfix/*)           default_base="origin/main" ;;
  develop|test|acceptance|main)
    fail "you are on '$branch'; work on a feature/, bugfix/ or hotfix/ branch and open a pull request" ;;
  master|develop-poc)
    fail "'$branch' must never be changed" ;;
  "") fail "detached HEAD; switch to a feature/, bugfix/ or hotfix/ branch" ;;
  *)  fail "branch '$branch' must start with feature/, bugfix/ or hotfix/ (Jenkins builds only those)" ;;
esac
base="${base:-$default_base}"
ok "branch $branch, compared with $base"

if ! git fetch --quiet origin 2>/dev/null; then
  warn "could not fetch origin; comparing with the last fetched $base (check: gh auth status)"
fi
git rev-parse --verify --quiet "$base" >/dev/null || fail "$base does not exist locally; run git fetch origin"

# 2. Working tree -------------------------------------------------------------------------
if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "uncommitted changes; commit or stash them first"
fi
ok "working tree clean"

# 3. Commit messages ----------------------------------------------------------------------
fork="$(git merge-base "$base" HEAD)"
mapfile -t commits < <(git rev-list --reverse "$fork..HEAD")
(( ${#commits[@]} )) || fail "no commits on $branch beyond $base"
bad=0
for c in "${commits[@]}"; do
  subject="$(git log -1 --format=%s "$c")"
  body="$(git log -1 --format=%b "$c")"
  problem=""
  if [[ -n "${body//[[:space:]]/}" ]]; then problem="has a body or trailer (one line only)"
  elif grep -qiE "co-authored-by|claude|anthropic" <<<"$subject"; then problem="mentions an AI tool or co-author"
  elif [[ "$subject" =~ [.,\;:!?]$ ]]; then problem="ends with punctuation"
  elif [[ "$subject" =~ (,|\;|:|!|\?)\  ]]; then problem="contains punctuation"
  elif [[ ! "$subject" =~ ^[A-Z] ]]; then problem="should start with a capital letter"
  elif (( ${#subject} > 100 )); then problem="longer than 100 characters"
  fi
  if [[ -n "$problem" ]]; then
    echo "  ${c:0:9} \"$subject\": $problem" >&2
    bad=1
  fi
done
(( bad == 0 )) || fail "commit messages break the rules above; reword them (git commit --amend or git rebase) before pushing"
ok "${#commits[@]} commit message(s) follow the rules"

git merge-base --is-ancestor "$base" HEAD \
  || warn "$branch is behind $base; rebase onto it before merging (git rebase $base)"

# 4. What changed, and which checks that needs -------------------------------------------
mapfile -t files < <(git diff --name-only "$fork" HEAD)
checks=()
add() { local c; for c in "${checks[@]}"; do [[ "$c" == "$1" ]] && return; done; checks+=("$1"); }

python_projects() {
  local p
  for p in libs/*/ services/*/; do
    [[ -f "${p}pyproject.toml" ]] && echo "${p%/}"
  done
  return 0
}

for f in "${files[@]}"; do
  case "$f" in
    ci/scripts/*|ci/jenkins/*.sh|.claude/skills/*/scripts/*) add "shellcheck" ;;
  esac
  case "$f" in
    frontend/*) add "frontend" ;;
    libs/*|pyproject.toml|uv.lock)
      while read -r p; do add "python:$p"; done < <(python_projects) ;;
    services/*/*)
      p="services/$(cut -d/ -f2 <<<"$f")"
      [[ -f "$p/pyproject.toml" ]] && add "python:$p" ;;
  esac
done
for c in "${checks[@]}"; do
  if [[ "$c" == python:services/* && -f "${c#python:}/alembic.ini" ]]; then add "migrations:${c#python:services/}"; fi
done

if (( ${#checks[@]} == 0 )); then
  ok "no code checks needed for these changes (${#files[@]} file(s); Jenkins still runs its own)"
  exit 0
fi
echo "checks for this branch: ${checks[*]}"
(( plan_only )) && exit 0

# 5. Environment --------------------------------------------------------------------------
free_mb="$(df -Pm . | awk 'NR==2 {print $4}')"
if (( free_mb < 2048 )); then
  fail "only ${free_mb} MB free; Docker-based checks fail or hang below about 2 GB. Free space first"
elif (( free_mb < 5120 )); then
  warn "only ${free_mb} MB free; Docker may become unstable"
fi
timeout 30 docker info >/dev/null 2>&1 || fail "Docker is not responding; start Docker Desktop and retry"
if command -v gh >/dev/null && ! gh api repos/Ali-Mazhar05/QuantSim-FYP --silent 2>/dev/null; then
  warn "GitHub CLI cannot reach Ali-Mazhar05/QuantSim-FYP; the push or PR may fail (gh auth status)"
fi

# 6. Run ----------------------------------------------------------------------------------
# python-ci.sh accepts a project path on newer branches, a service name on older ones
if grep -q 'project=' ci/scripts/python-ci.sh; then path_mode=1; else path_mode=0; fi

for c in "${checks[@]}"; do
  echo "==> $c"
  case "$c" in
    shellcheck) ci/scripts/shellcheck.sh ;;
    frontend)   ci/scripts/frontend-ci.sh ;;
    python:*)
      p="${c#python:}"
      if (( path_mode )); then ci/scripts/python-ci.sh "$p"
      elif [[ "$p" == services/* ]]; then ci/scripts/python-ci.sh "${p#services/}"
      else warn "this branch's python-ci.sh cannot check $p; Jenkins will"; fi ;;
    migrations:*) ci/scripts/migration-check.sh "${c#migrations:}" ;;
  esac || fail "$c failed"
done

ok "all checks passed; safe to push: git push -u origin $branch"
