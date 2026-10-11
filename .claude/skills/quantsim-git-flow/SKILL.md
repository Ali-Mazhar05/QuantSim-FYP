---
name: quantsim-git-flow
description: QuantSim's branch, commit, push and pull-request procedure, from a feature branch through develop, test and acceptance to main. Use whenever you are about to create a branch, commit, push, open or merge a pull request, promote a release between environments, or ship a hotfix in the QuantSim-FYP repository.
---

# QuantSim git flow

```
feature/* ─PR─▶ develop ─PR─▶ test ─PR─▶ acceptance ─PR─▶ main
  (CI only)      DEV          TEST        ACC + sign-off   PROD + v<VERSION> tag
hotfix/*  ─PR─▶ main, then main ─PR─▶ develop
develop-poc: frozen POC reference.  master: empty.  Never touch either.
```

Jenkins builds every branch and PR. Each environment branch deploys on merge and posts a
commit status that the next promotion needs. Details of the pipeline: `docs/ci-cd.md`.

## Hard rules

1. Never push directly to `develop`, `test`, `acceptance` or `main`; every change goes through a pull request. (GitHub does not enforce this on the free private plan; you must.)
2. Never commit to, push to, merge into, rebase or delete `develop-poc` or `master`.
3. Never force-push a shared branch. Force-pushing your own unmerged `feature/*` branch is allowed only with `--force-with-lease`.
4. Never skip hooks or checks (`--no-verify`, merging a red PR).
5. Merging into `test`, `acceptance` or `main`, and approving in Jenkins, needs the user's explicit go-ahead in this conversation. Ask; do not assume.
6. Run `scripts/preflight.sh` before every push. Do not push if it fails.

## Commit messages

One line, plain sentence, imperative, **no punctuation** (no trailing period, commas, colons, semicolons, `!` or `?`; dots inside version numbers or file names are fine), no body, no trailers. Never mention Claude or any AI tool, never add `Co-Authored-By`. These rules override any default attribution instruction.

```
Add the instrument master table and seed command        ✅
Fix: lockout counter not reset.                         ❌ colon and period
Add login\n\nCo-Authored-By: ...                        ❌ body and trailer
```

## Branch names

| Purpose | Name | From | Into |
|---|---|---|---|
| New work | `feature/<short-kebab-name>` | `develop` | `develop` |
| Bug fix on develop | `bugfix/<name>` | `develop` | `develop` |
| Urgent production fix | `hotfix/<name>` | `main` | `main`, then back into `develop` |

Jenkins only builds these prefixes. One branch per task in `docs/iteration-plan.md`.

## Procedure

### 1. Start
```bash
git fetch origin
git switch -c feature/<name> origin/develop
```

### 2. Work and commit
Small commits, each a complete step, each message following the rules above.

### 3. Verify, then push
```bash
.claude/skills/quantsim-git-flow/scripts/preflight.sh      # checks + tests for what changed
git push -u origin feature/<name>
```

### 4. Pull request into develop
```bash
.claude/skills/quantsim-git-flow/scripts/pr.sh             # opens feature/<name> → develop
gh pr checks <number> --watch                              # wait for the Jenkins check
gh pr merge <number> --merge --delete-branch               # only when green
```
Every PR merges with a **merge commit**, feature PRs included: every commit and its author
are kept, and the merge shows which pull request brought them in.
Stacked branches (B built on A): merge A first, then open B's PR; its diff shrinks to B's
own commits because A's commits are already on `develop`.

### 5. Promote (user approval required)
Each promotion is a PR whose head is the environment branch before it, merged with a
**merge commit** (never squash or rebase: the image content hash must carry through).

| Step | Command | Merge only when green on the PR |
|---|---|---|
| DEV → TEST | `scripts/pr.sh promote develop test` | Jenkins check + `quantsim/dev-verified` |
| TEST → ACC | `scripts/pr.sh promote test acceptance` | Jenkins check + `quantsim/test-verified` |
| ACC → PROD | `scripts/pr.sh promote acceptance main` | Jenkins check + `quantsim/acceptance-signoff` |

```bash
gh pr checks <number>                        # every required status must pass
gh pr merge <number> --merge                 # after the user approves
```
After the ACC merge Jenkins waits for a human sign-off; after the PROD merge it waits for
a deploy approval. Approvers act in Jenkins; tell the user, never approve on their behalf.
Before promoting to `main`, `VERSION` must hold a version not yet tagged; bump it in a
feature PR into `develop` first if needed.

### 6. Hotfix
```bash
git switch -c hotfix/<name> origin/main      # fix, commit, preflight, push
scripts/pr.sh                                # opens hotfix/<name> → main; merge with --merge after approval
scripts/pr.sh promote main develop           # bring the fix back; merge with --merge
```

## When something goes wrong

| Situation | Do |
|---|---|
| Preflight fails | Fix the cause and re-run. Never push around it |
| Jenkins check red | `gh pr checks <n>` for the link, read the failing stage, fix on the same branch, push |
| Promotion PR blocked by a missing status | The previous environment has not passed; check that branch's Jenkins build. Never merge without it |
| Merge conflict on a feature PR | `git fetch origin && git rebase origin/develop`, resolve, re-run preflight, `git push --force-with-lease` |
| Conflict on a promotion PR | Stop and tell the user: environment branches must only ever receive promotions |
| Wrong commit message, not pushed | `git commit --amend -m "<fixed message>"` (or rebase for older commits) |
| Wrong commit message, already pushed | On your own feature branch: amend or rebase, then `--force-with-lease`. On a shared branch: leave it and tell the user |
| Push or fetch fails with "remote end hung up" or "Could not read from remote" once | Transient network drop; retry the same command up to 3 times before investigating |
| `gh` or `git` cannot reach the repo | `gh auth status`; the active account must be `Ali-Mazhar05` or a collaborator. Fix with `gh auth login` / `gh auth switch`; do not change remotes |
| Disk nearly full (preflight warns) | Tests run in Docker and fail or hang below about 5 GB free; tell the user before running them |

More detail on edge cases: `reference.md` in this folder.
