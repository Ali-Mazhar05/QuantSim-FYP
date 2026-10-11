#!/usr/bin/env bash
# Opens the right pull request for the QuantSim flow and prints how to merge it.
#
#   pr.sh                         current feature/, bugfix/ or hotfix/ branch into its target
#   pr.sh --title "<one line>"    same, with an explicit title (default: first commit)
#   pr.sh promote <from> <to>     promotion: develop test | test acceptance |
#                                 acceptance main | main develop (after a hotfix)
#
# Prints the URL of an existing open PR instead of opening a duplicate.
set -euo pipefail

repo="Ali-Mazhar05/QuantSim-FYP"
fail() { echo "PR FAIL: $*" >&2; exit 1; }

command -v gh >/dev/null || fail "GitHub CLI (gh) is not installed"
gh api "repos/$repo" --silent 2>/dev/null \
  || fail "cannot reach $repo; run gh auth status (active account must have access)"

title=""
if [[ "${1:-}" == "promote" ]]; then
  from="${2:?usage: pr.sh promote <from> <to>}"
  to="${3:?usage: pr.sh promote <from> <to>}"
  case "$from>$to" in
    "develop>test")       needs="Jenkins check and quantsim/dev-verified" ;;
    "test>acceptance")    needs="Jenkins check and quantsim/test-verified" ;;
    "acceptance>main")    needs="Jenkins check and quantsim/acceptance-signoff" ;;
    "main>develop")       needs="Jenkins check (brings a hotfix back into develop)" ;;
    *) fail "not a promotion: $from -> $to (allowed: develop>test, test>acceptance, acceptance>main, main>develop)" ;;
  esac
  head="$from"; base="$to"; method="--merge"
  sha="$(git rev-parse --short "origin/$from" 2>/dev/null || echo unknown)"
  [[ "$to" == "develop" ]] && verb="Bring" || verb="Promote"
  title="$verb $from into $to"
  body="$verb \`$from\` at \`$sha\` into \`$to\`.

Merge only when these are green on this PR: $needs.
Merge with **Create a merge commit** so the built images carry through unchanged."
else
  [[ "${1:-}" == "--title" ]] && title="${2:?}"
  head="$(git branch --show-current)"
  case "$head" in
    feature/*|bugfix/*) base="develop"; method="--merge --delete-branch" ;;
    hotfix/*)           base="main";    method="--merge --delete-branch" ;;
    *) fail "run from a feature/, bugfix/ or hotfix/ branch, or use: pr.sh promote <from> <to>" ;;
  esac
  # Ask the GitHub API (retried: home connections drop git traffic now and then)
  remote_sha=""
  for _ in 1 2 3; do
    remote_sha="$(gh api "repos/$repo/branches/$head" --jq .commit.sha 2>/dev/null)" && break
    sleep 3
  done
  [[ -n "$remote_sha" ]] \
    || fail "$head is not on GitHub yet; run preflight.sh, then git push -u origin $head"
  [[ "$(git rev-parse HEAD)" == "$remote_sha" ]] \
    || fail "local $head differs from GitHub; push your latest commits first"
  fork="$(git merge-base "origin/$base" HEAD)"
  [[ -n "$title" ]] || title="$(git log --reverse --format=%s "$fork..HEAD" | head -1)"
  commits="$(git log --reverse --format='- %s' "$fork..HEAD")"
  body="Commits:
$commits

Preflight passed locally (.claude/skills/quantsim-git-flow/scripts/preflight.sh)."
  needs="Jenkins check"
fi

existing="$(gh pr list --repo "$repo" --head "$head" --base "$base" --state open --json url --jq '.[0].url')"
if [[ -n "$existing" ]]; then
  url="$existing"
  echo "already open: $url"
else
  url="$(gh pr create --repo "$repo" --head "$head" --base "$base" --title "$title" --body "$body")"
  echo "opened: $url"
fi

number="${url##*/}"
cat <<EOF

next:
  gh pr checks $number --repo $repo --watch      wait for: $needs
  gh pr merge $number --repo $repo $method$( [[ "$base" != "develop" || "$head" == main ]] && echo "      only after the user approves" )
EOF
