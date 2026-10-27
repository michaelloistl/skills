---
name: drive-spec
description: "Build a spec's tracer-bullets, each in its own worktree, into one draft PR."
disable-model-invocation: true
---

# drive-spec

`/drive-spec <spec-issue> [--base <branch>] [--sequential] [--dry-run]`

Drive a spec issue from its tracer-bullet issues to one draft PR `spec branch → base`. Each slice is built in its own worktree and merged into the spec branch, which lives in a worktree of its own. The checkout you are standing in is never touched, so several sessions can drive several specs in one repo at once.

The tickets are a task graph. Slices whose blockers have all closed form the **frontier**. State lives only in the tracker and the branches, so any session can resume any spec, and the same slice never builds twice.

`drive-spec`, the script beside this file, runs every deterministic part of a step; `drive-spec --help` lists its commands. Its refusals (exit 2) name the broken rule: fix that, never route around it.

Reference, read when a step points at it:

- [`TRACKER.md`](TRACKER.md) — discovery, blockers, labels, the progress and status comments, integration and landing, PRs, halting.
- [`WORKTREES.md`](WORKTREES.md) — root, naming, notes directory, create, bootstrap, resume rules, cleanup.
- [`EXPLORER.md`](EXPLORER.md), [`IMPLEMENTER.md`](IMPLEMENTER.md), [`REVIEWER.md`](REVIEWER.md), [`REVIEW-FIXER.md`](REVIEW-FIXER.md) — the subagent briefs. The script fills each into a file and prints `Read <file> and follow it.`: that sentence is the subagent's whole prompt.
- [`STATUS.md`](STATUS.md) — the status file, its states, how to ask the operator a question, and the inbox.

Every step ends in a `drive-spec` command that marks the next step begun in the status file per STATUS.md; the step names it. Its exit code is the verdict, so run each command bare, with nothing piped after it, in the foreground. `drive-spec next <spec>` prints the command that carries a run on, from its status file: run it first when resuming. Exit 6 means a gate is still running: the command returned before the Bash timeout, and running it again picks up where it stopped, so `verify` and `integrate` always take `--wait-minutes 9` and a 10-minute Bash timeout, and nothing runs in the background. Commands that read the dispatcher's inbox (STATUS.md, Inbox) exit 5 while notes wait: act on them, then run the command again. A decision only the operator can make goes through `drive-spec ask` and `drive-spec answered` (STATUS.md, Questions).

Communicate with subagents through context pointers: issue numbers, worktree paths, research notes, the `drive-spec verify` command. Everything else they read themselves.

An interim notification from a background subagent gets a one-line status; act on its final report.

## Steps

1. **Resolve the run.** For each of `baseBranch`, `bootstrap`, `verify`, `parallel`, `maxSlices`, `localOnly`: a flag wins, then `.claude/drive-spec.json` in the repo root, then the default. Defaults: repository default branch, no bootstrap, verify gate read from the repo's `CLAUDE.md` or `AGENTS.md`, parallel, no ceiling, no local-only slices. `--sequential` sets `parallel` to false. Resolve the worktree root per WORKTREES.md. A cloud session is one where `CLAUDE_CODE_REMOTE` is `true`. Pin the resolved gate with `drive-spec gate <spec> '<verify>' --base <base>`, wherever it came from: every verdict in the run comes from `drive-spec verify`, which runs the pinned gate and only that gate; pinning marks the run's start, from which `maxSlices` counts landings, and writes `base` to the status file for every later command. Done when every value is printed with where it came from, and the gate is pinned.

   `localOnly` marks slices only the developer's machine can prove, such as tests that need a desktop app: `label` names them, and `proof` is a file in the repo saying how to prove one beyond the verify gate. In a cloud session these slices are **held**: never built, and anything they block waits. Locally they build one at a time, and their implementer also follows `proof`.

2. **Guard the spec.** Run `drive-spec plan <spec>`, the script beside this file. It discovers the tracer-bullets and their blockers, orders them, and gives each slice's state: `closed`, `open-pr`, `in-flight`, `todo` or `held`. Exit 2 refuses the spec, with the reason on its `refuse:` line: run `drive-spec finish <spec> refused`, and stop. Done when the plan is printed: printed without `--json` in step 2, it also marks step 3 begun. Whenever a later step needs slice states again, run `drive-spec plan <spec> --json` rather than re-deriving them.

3. **Open the spec worktree.** Branch `agent/local-spec-<n>-<slug>` — the `local-` segment is load-bearing: a repo whose CI advances specs off merges into `agent/spec-*` would otherwise dispatch the next slice itself on every merge here and build it twice. `drive-spec open <spec> --base <base>` reuses the worktree, resumes the branch from origin, or cuts it from `origin/<base>` and pushes it, bootstraps a new worktree, and writes `branch` and `base` to the status file. Done when it prints the worktree: it is then on the spec branch at origin's HEAD.

4. **Preview.** `drive-spec preview <spec>`, with `--sequential` and `--max` as resolved in step 1, prints base, spec branch, worktree root, mode, ceiling and the plan, and posts or refreshes the progress comment. With `--dry-run`, add it to the command, which pauses the run there, and stop.

5. **Explore.** `drive-spec explore <spec>` writes the explorer brief; hand it to one general-purpose subagent. It writes notes for each open slice, `coverage.md` mapping every spec requirement to the slice that owns it, `questions.md` with each decision the spec leaves to the operator, and `conflicts.md`. Done when `drive-spec explored <spec>` exits 0. It refuses, naming what to do, while a file is missing or older than the run, a requirement is `unmapped`, or a question has no answer: ask each through `drive-spec ask <spec> '<question>' --ref Q<k>`, record each unmapped requirement's answer in `coverage.md`, then run it again. Exit 3: `conflicts.md` lists conflicts, and the command has halted the run before any build and posted the list; stop. The operator settles each conflict in the issues and resumes.

6. **Build the frontier.** Repeat until every slice is closed, the ceiling is reached, or only held slices and the slices they block remain:
   - Pick: `drive-spec frontier <spec> --running <m>,…`, naming the slices whose implementer is running now (`--sequential`, `--max` as resolved in step 1). Each line is an action: `build` or `continue` a slice, or `integrate` one whose PR is already open. It applies the mode, the ceiling, held slices, and one `localOnly` slice at a time. `wait` means let a running implementer finish; `stop:` ends the loop. Exit 2: a slice carries `agent:blocked`; finish the run as halted.
   - For each `build`, `continue` or `integrate`: `drive-spec start <spec> <m>` restores or opens its worktree, bootstraps it, labels it `agent:in-progress`, and writes the implementer brief. Hand the prompt it prints to an implementer subagent, in the background when parallel. An `integrate` slice goes straight to the integration queue. The implementer is done when every change is committed and `drive-spec verify` is green on that HEAD. Completed slices enter the integration queue in finish order.
   - Integrate one slice at a time: `drive-spec integrate <spec> <m> --report - --wait-minutes 9`, the implementer's `Deviations:`, `Unverified:` and, for a `localOnly` slice, `Proof:` lists on stdin. It opens the slice PR, merges the latest spec branch into the slice, verifies that exact integration, writes the gate, SHA, verdict and proof into the PR's `Verification:` section, pushes, and merges the PR at the verified HEAD, again whenever the spec branch moves. Exit 6: run `drive-spec integrate <spec> <m> --wait-minutes 9` again. Exit 3 is a conflict: a merger subagent in the slice worktree runs the `git merge` it names, resolves and commits, then integrate again. Exit 4 is red. Exit 2 refuses and says why: fix that, never route around it.
   - Land: `drive-spec land <spec> <m>`. It closes the issue naming the PR, removes the slice worktree and branches, opens the draft spec PR at the first landing, refreshes the progress comment, and writes status. Only then integrate the next completed slice.
   - A slice whose implementation or integration reports red halts the run: `drive-spec halt <spec> <m> <why>`. Every later slice assumes this one landed.
   - `stop: ceiling`: `drive-spec finish <spec> ceiling`. `stop: held`: `drive-spec finish <spec> held`. `stop: done`: go to step 7.

7. **Review the whole.** Run `drive-spec review <spec>` and do what it prints, until it prints `review clean`. Each call is one of: a round's reviewer brief (hand it to a reviewer subagent, which writes the round's findings file); a round's fixer brief, holding only that round's **rule** findings, each citing the written rule it breaks, and its **bug** findings, each saying how the change fails (hand it to an implementer subagent in the spec worktree); or clean. Between a fixer and the next round, `review` pushes the verified fixes itself. A **judgement** finding never goes to a fixer: the rounds collect them as the left list. A fixer that reports a fix would change an operator answer has asked a question: `drive-spec ask` it. Past `reviewRounds` (default 3) with findings to fix still open, `review` refuses until the operator answers whether to go on. Done when `drive-spec reviewed <spec>` exits 0: it refuses until the last round is a clean review of the pushed, green HEAD, and keeps the rounds' judgement calls for `confirm`.

8. **Confirm the spec PR.** `drive-spec confirm <spec>`. With every slice closed and the spec branch HEAD green, it rewrites the draft's body to `Closes #<spec>`, the slices, a `Verification:` section (the gate, the spec HEAD's verdict, each slice's verdict and local proof), and the `Unverified:` and `Deviations:` lists their PRs reported, opens the draft first when absent, and keeps it draft, with step 7's `Left from review:` list when there is one.

9. **Clean up.** `drive-spec cleanup <spec>` removes the spec worktree, any slice worktree still present, and the notes directory, prunes, prints the PR URL, and marks step 10 begun in the status file. It refuses while a slice is open or the spec worktree holds uncommitted or unpushed work. The spec branch stays on origin until the PR merges.

10. **Review and fix the spec PR.** Run `/review-fix-pr <pr>` on the spec PR. It runs after step 9 because it opens the PR head in a worktree of its own and refuses a head checked out elsewhere. The PR stays draft. A run whose PR already carries a `review-fix-pr done` comment newer than the spec branch's last push skips this step. Its fix pass going red halts the run: `drive-spec finish <spec> halted --why '<why>' --step review-pr --resume '/review-fix-pr <pr>'`. Done when its status comment is on the PR; then `drive-spec qa <spec>`, which marks step 11 begun.

11. **QA the spec PR.** Run `/qa-pr <pr>` on the spec PR: it runs the app at the PR head, walks every scenario in a browser, and posts the evidence on the PR. A run whose PR already carries a `qa-pr done` comment naming the spec branch's HEAD skips this step. A failed scenario halts the run: `drive-spec finish <spec> halted --why '<why>' --step qa-pr --resume '/qa-pr <pr>'`. Done when its comment is on the PR with no failed scenario; then `drive-spec finish <spec> done`. Scenarios it could not verify stay listed in its comment for the operator.

Every run ends with `drive-spec finish` or `drive-spec halt`, never both: they post the status comment the operator is notified by, and write the final status. Only `--dry-run` ends without either, on `drive-spec preview --dry-run`'s `paused` status. `finish` refuses an outcome the tracker contradicts, such as `done` with a slice still open.
