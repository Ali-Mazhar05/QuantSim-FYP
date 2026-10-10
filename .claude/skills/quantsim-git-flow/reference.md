# QuantSim git flow: reference

Edge cases behind `SKILL.md`. Read only the section you need.

## Why the merge methods differ

| PR | Method | Reason |
|---|---|---|
| `feature/*` → `develop` | rebase | Linear history on `develop`, and every commit with its author survives (the FYP rubric scores each member's commit history). Squash would collapse them |
| promotions (`develop` → `test` → `acceptance` → `main`) | merge commit | Images are tagged by the *content* of the files that define them; a merge commit keeps that content identical, so TEST, ACC and PROD reuse the image DEV built and verified. Rebase or squash on these branches would also break the commit statuses Jenkins posted |
| `hotfix/*` → `main`, `main` → `develop` | merge commit | Same as promotions |

## Statuses that gate promotion

Jenkins posts them on the exact commit it verified; the promotion PR's head is that commit.

| Status | Posted when |
|---|---|
| `quantsim/dev-verified` | DEV deployed and passed its smoke test |
| `quantsim/test-verified` | TEST deployed and passed its smoke test |
| `quantsim/acceptance-signoff` | An approver accepted ACC in Jenkins (failure if rejected) |

Check them: `gh pr checks <n> --repo Ali-Mazhar05/QuantSim-FYP`, or
`gh api repos/Ali-Mazhar05/QuantSim-FYP/commits/<sha>/statuses --jq '.[].context'`.

## Stacked branches

When branch B builds on unmerged branch A:
1. Open A's PR; wait for green; merge (rebase).
2. `git switch B && git fetch origin && git rebase --onto origin/develop A B`
   (drops A's old commits, which now exist on `develop` under new hashes).
3. Re-run `preflight.sh`, `git push --force-with-lease`, then open B's PR.

Open B's PR only after A merges, or its diff will show A's commits too.

## Releasing a version

`main` refuses to release a version that is already tagged. Before promoting to `main`:
1. Feature PR into `develop` that changes `VERSION` (e.g. `0.1.0` → `0.2.0`), commit
   message like `Bump the version to 0.2.0`.
2. Promote it through `test` and `acceptance` like any change.

## Undoing a change

| Case | Do |
|---|---|
| Bad feature already in `develop` | `git switch -c bugfix/revert-<name> origin/develop && git revert <sha>`, then the normal PR flow |
| Bad release running in an environment | Roll back the environment through the CI/CD procedure (Jenkins), then fix forward with a bugfix PR |
| Commit on the wrong branch, not pushed | `git switch -c feature/<right-name>` keeps it; then `git switch <wrong> && git reset --hard origin/<wrong>` only if that branch is yours and unshared |

Never rewrite history on `develop`, `test`, `acceptance` or `main`.

## Machine setup (once per clone)

```bash
git config --local user.name "<GitHub username>"
git config --local user.email "<GitHub noreply email>"
git config --local credential.https://github.com.username "<GitHub username>"
gh auth login            # as an account with access to Ali-Mazhar05/QuantSim-FYP
gh auth status           # the active account must be that one
```
The repo-local credential username matters on machines where another GitHub account is
the global default.

## Things that look harmless but are not

- Opening a PR from `develop-poc`, or basing work on it: it is a frozen reference.
- Creating `master` or pushing to it.
- Merging a promotion PR because "the code is the same": without the status, the
  previous environment never proved it.
- Running `preflight.sh` on a nearly full disk: Docker Desktop on Windows stops
  responding when the disk fills, which also takes Jenkins, DEV and TEST down.
- Committing `ci/jenkins/secrets/*`, `ci/jenkins/.env`, `*.dec.env` or a stray
  `admin_password`: all are secrets. `git status` before every commit.
