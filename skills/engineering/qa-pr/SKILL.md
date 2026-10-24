---
name: qa-pr
description: "Turn a PR, open or merged, into a step-by-step browser QA plan."
disable-model-invocation: true
---

# qa-pr

`/qa-pr <pr>`

Read one PR and hand the operator a QA plan: every behaviour it changed, as a **scenario** they can walk through in their local browser. The run is read-only: it prints the plan, and leaves the checkout, the server, and the PR untouched.

GitHub goes through the REST API with `gh api`, never `gh pr`: those use GraphQL, which the cloud-session GitHub proxy rejects. Resolve the repository once:

```sh
repo=$(git remote get-url origin | sed -E 's#(\.git)?/*$##' | awk -F'[/:]' '{print $(NF-1)"/"$NF}')
```

## Steps

1. **Resolve the PR.** `gh api "repos/$repo/pulls/<pr>" --jq '{number, title, state, merged, merge_commit_sha, body, base: .base.ref, head: .head.ref, head_sha: .head.sha}'`. The linked issue is the first `#<m>` after a closing keyword (`Closes`, `Fixes`, `Resolves`, any tense) in the body; read it with `gh api repos/$repo/issues/<m>`. Done when state, base, head, and intent (PR body plus issue) are in hand.

2. **Read the diff.** `git fetch origin`, then take the PR's own change, never base drift since:
   - merged: `git diff <merge_commit_sha>^1 <merge_commit_sha>` (for a squash or rebase merge, `gh api repos/$repo/pulls/<pr>/files` is the authoritative file list);
   - open: `git diff origin/<base>...<head_sha>`.

   Read the full hunks, then the code around them: routes, controllers, views, components, policies, flags. Done when you can say, per hunk, what a user would see differently.

3. **Map hunks to surfaces.** A **surface** is a place in the running app where a change is visible: a URL, a component state, an email, a background effect seen in the UI. For each behaviour change derive the scenarios a careful QA tester would run: the happy path, then every edge the diff itself encodes (each new branch, validation, permission check, empty or error state), then a regression check on any shared code the PR touched. Done when every hunk traces to a scenario or to the not-browser-testable list, with a reason.

4. **Work out setup.** Where the operator runs it:
   - merged: their `<base>` once `git merge-base --is-ancestor <merge_commit_sha> origin/<base>` holds; pull first if local `<base>` lags.
   - open: a worktree on the PR head, `git worktree add .claude/worktrees/pr-<pr> <head_sha>`.

   Then everything a scenario needs before step one: migrations, env vars, feature flags, the user or role to log in as, and the records that must exist. Give each missing record as a paste-ready snippet (`bin/rails runner` / console, or the repo's equivalent), built from the actual models and factories. Done when a fresh dev database could run every scenario.

5. **Print the plan** in the format below. Done when printed.

## Plan format

```markdown
# QA: #<pr> <title> (<open|merged>)

<one or two lines: what the PR is meant to do>

## Setup
- Checkout: <command>
- Server: `/dev-up` (or the repo's start command)
- Data: <snippets>
- Log in as: <user / role>

## Scenarios
### 1. <behaviour, in user terms>
URL: <path>
Given: <precondition>
1. <click / type / navigate>
2. …
Expect: <exact visible result>

## Not browser-testable
- `<file>`: <why> → <how to verify instead: spec, console, log>
```

Order scenarios from the PR's core behaviour outward to edges and regressions. Write every **Expect** as something the operator can see on screen: exact copy, element, redirect, or count.
