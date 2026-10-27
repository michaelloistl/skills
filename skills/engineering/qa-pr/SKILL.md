---
name: qa-pr
description: "QA a PR, open or merged: run the app at its head, walk every changed behaviour in a browser, and post the evidence on the PR."
---

# qa-pr

`/qa-pr <pr> [--plan-only]`

Read one PR, turn every behaviour it changed into a **scenario**, then run each one yourself against the app at the PR's code and post what you saw on the PR. The PR's author is not the verifier, and neither is the operator: you are. With `--plan-only`, stop after the plan and print it for the operator to walk instead.

The run commits nothing to the PR. It works in a worktree of its own, on a database of its own, starts and stops its own server, and writes two things to GitHub: its screenshots, to the **evidence branch**, and one comment. It runs the same on macOS and Linux.

Keys below come from `.claude/drive-spec.json` in the **base checkout**, `<base>` = `$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")`; each is optional. The `qa*` keys name **QA tooling**, and the code under test may predate it: run every `qa*` command, and import `qaHelpers`, from `<base>`, with `export QA_ROOT=<worktree>` in the same shell, which points them at the worktree's code and database.

GitHub goes through the REST API with `gh api`, never `gh pr`: those use GraphQL, which the cloud-session GitHub proxy rejects. Resolve the repository once:

```sh
repo=$(git remote get-url origin | sed -E 's#(\.git)?/*$##' | awk -F'[/:]' '{print $(NF-1)"/"$NF}')
```

## Steps

1. **Resolve the PR.** `gh api "repos/$repo/pulls/<pr>" --jq '{number, title, state, merged, merge_commit_sha, body, base: .base.ref, head: .head.ref, head_sha: .head.sha}'`. The linked issue is the first `#<m>` after a closing keyword (`Closes`, `Fixes`, `Resolves`, any tense) in the body; read it with `gh api repos/$repo/issues/<m>`. The **SHA under test** is `head_sha` for an open PR, `merge_commit_sha` for a merged one. Done when state, base, SHA under test, and intent (PR body plus issue) are in hand.

2. **Read the diff.** `git fetch origin`, then take the PR's own change, never base drift since:
   - merged: `git diff <merge_commit_sha>^1 <merge_commit_sha>` (for a squash or rebase merge, `gh api repos/$repo/pulls/<pr>/files` is the authoritative file list);
   - open: `git diff origin/<base>...<head_sha>`.

   Read the full hunks, then the code around them: routes, controllers, views, components, policies, flags. Read the PR body's `Unverified:` list too, when it has one: each line is a behaviour its author could not prove, and it gets a scenario. Done when you can say, per hunk, what a user would see differently.

3. **Map hunks to surfaces.** A **surface** is a place in the running app where a change is visible: a URL, a component state, an email, a background effect seen in the UI. For each behaviour change derive the scenarios a careful QA tester would run: the happy path, then every edge the diff itself encodes (each new branch, validation, permission check, empty or error state), then a regression check on any shared code the PR touched. Done when every hunk traces to a scenario or to the not-browser-testable list, with a reason and the test in the repo's gate that covers it, or `none`.

4. **Work out setup.** Everything a scenario needs before its first step: migrations, env vars, feature flags, the user or role to log in as, and the records that must exist. Give each missing record as a paste-ready snippet (`bin/rails runner` / console, or the repo's equivalent), built from the actual models and factories. When `qaInventory` is set, run it after `qaReset` and take IDs, names and dates from its output instead of probing the seed. Write them against a fresh database: `qaReset` builds one from the schema and the repo's seed, and the snippets add to that seed, never to a developer's database. Done when that database could run every scenario. With `--plan-only`, print the plan in the format below, with the checkout as `git worktree add .claude/worktrees/qa-<pr> <sha>`, and stop.

5. **Start the app.** `git worktree add --detach <root>/qa-<pr> <sha under test>`, where `<root>` is `worktreeRoot` from `.claude/drive-spec.json`, else `.claude/worktrees`; reuse it when it already sits at that SHA. Run `bootstrap` there, when set, then `qaReset` from `<base>`, when set. Start the server on a free port: `qaServer <port>` when set, else the repo's start command from `CLAUDE.md` or `AGENTS.md` (`/dev-up` for a Rails app). Run it as a process group of its own, with its output in `<qa>/server.log`, where `<qa>` is `$(git rev-parse --git-common-dir)/qa-pr/<pr>`: `perl -e 'setpgrp(0,0); exec @ARGV' <command> > <qa>/server.log 2>&1 < /dev/null &` works on both macOS and Linux, and later `kill -- -<pid>`. Run the setup snippets prefixed with `qaRun`, when set, so they reach the server's database. Done when the app answers on its URL. An app that will not start leaves every scenario not verified: go to step 7 and say why.

6. **Run every scenario.** Drive a real browser: the session's browser tool when it has one, else headless Chromium through Playwright (`<base>/node_modules/.bin/playwright install chromium` once, so the browser matches the Playwright `qaHelpers` resolves; on Linux add `--with-deps` if launch reports missing libraries; then a script per scenario under `<qa>`, after `ln -sf <base>/node_modules <qa>/node_modules` so the scripts resolve `playwright`). When `qaHelpers` names a module, import it from `<base>` by absolute path for login, the repo's widgets and its page readers, and run the scripts with `QA_ROOT` set so its login reaches the QA database. Extend it in `<base>` when a widget or reader it lacks costs you a debugging round. Each script prints every scenario's `Saw:` line: the copy, counts, URLs and filenames it read off the page. Per scenario, do its steps, then read the page and compare it against **Expect**, and read the lines `server.log` gained during it. Its outcome is one of:
   - **passed**: you saw the Expect on screen, and the log shows no error the scenario raised;
   - **failed**: what you saw differs, or the log shows an error: record both, verbatim;
   - **not verified**: you could not run it (an external service, data you could not create, a step no browser can take): record why, and how the operator can check it.

   Save a screenshot of each scenario's last state as `<qa>/<k>.png`, viewport-sized, scrolled to what **Saw** names; add `<qa>/<k>-<n>.png` for an earlier state the outcome rests on, such as the page before a click. Passed means observed: a scenario you did not watch pass is not verified. Done when every scenario has an outcome and its evidence.

7. **Post and clean up.** Upload the screenshots: `<skill dir>/scripts/upload-evidence.sh $repo <branch> <pr>/<sha12> <qa>/*.png`, where `<branch>` is `qaEvidenceBranch`, else `qa-evidence`. It creates that branch as an orphan the first time, commits each file through the contents API, and prints `<file><TAB><url>` per file; the URLs render in a comment for anyone who can read the repo. An upload that fails leaves the report without images: say so in its last line. Write each scenario's `Saw:` from the line its script printed, every figure unedited. Post the report below as one comment: `gh api repos/$repo/issues/<pr>/comments -f body=… --silent`. Then stop the server's process group, and remove the worktree with `git worktree remove --force` and `git worktree prune` when step 5 created it. `<qa>` stays, with the screenshots and the log, and so does the database `qaReset` built. Print the PR URL and the counts. Done when the comment is on the PR and the server is down.

## Plan format

`--plan-only` prints this; a full run uses it as its working list.

```markdown
# QA: #<pr> <title> (<open|merged>)

<one or two lines: what the PR is meant to do>

## Setup
- Checkout: <command>
- Server: `/dev-up` (or the repo's start command)
- Database: `qaReset` (fresh, seeded), or the repo's dev database when unset
- Data: <snippets, run with `qaRun`>
- Log in as: <user / role> (`qaLogin` in `.claude/drive-spec.json`, when set, is a command that prints one as `email<TAB>password`)

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

Order scenarios from the PR's core behaviour outward to edges and regressions. Write every **Expect** as something visible on screen: exact copy, element, redirect, or count.

## Report

The comment's first line is its verdict, and callers read it: `/drive-spec` skips QA on a PR that already carries a `qa-pr done` comment naming the head it would test, and halts on any failed scenario.

```markdown
qa-pr done at <sha12>: <p> passed, <f> failed, <u> not verified.

### 1. <behaviour> — <passed|failed|not verified>
URL: <path>
Did: <the steps as you ran them>
Saw: <exact copy, element, redirect or count on screen>
Server log: <no errors | the lines it gained, verbatim>

![<k>](<url>)

## Not verified
- <scenario>: <why> → <how the operator can check it>

## Not browser-testable
- `<file>`: <why> → <the test that covers it, or `none`>
```

Leave out a section with nothing in it. Each scenario embeds every screenshot it saved, in order. A not-verified scenario embeds its last state when it has one.
