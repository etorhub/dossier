---
name: github-pull-request
description: >-
  Open a GitHub pull request for this repository using the GitHub CLI (gh).
  Use when the user asks to create a PR, open a pull request, or publish a
  branch for review. Ensures the branch is pushed to origin before gh pr create.
---

# GitHub pull request

Canonical detail: **CLAUDE.md** → section “Pull requests (GitHub)”, and **`.cursor/rules/pull-requests.mdc`**.

## Steps (agent)

1. `git status` — confirm the right branch and that intended changes are committed (or ask the user about uncommitted work).
2. `which gh` — if missing, tell the user to install [GitHub CLI](https://cli.github.com/) and run `gh auth login`.
3. `git fetch origin` then `git ls-remote --heads origin <head-branch>` — if empty, **`git push -u origin <head-branch>`** before creating the PR.
4. `git log origin/<base>..origin/<head> --oneline` — confirm there are commits to merge (default base: `main`, or match `gh repo view --json defaultBranchRef`).
5. `gh pr create --base main --head <head-branch> --title "…" --body "…"`, or from a checked-out tracking branch: `gh pr create --fill` / interactive `gh pr create`.
6. Return the PR URL; optionally mention `gh pr view --web`.

## If `gh pr create` fails

Interpret GitHub’s message: missing remote branch (push again), wrong base/head, or branch already merged. Re-run fetch and compare `origin/main` and `origin/<head>`; do not assume the problem is auth unless `gh auth status` fails.
