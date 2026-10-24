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
- [`IMPLEMENTER.md`](IMPLEMENTER.md) — the brief handed to each implementer subagent.
- [`STATUS.md`](STATUS.md) — the status file, its states, how to ask the operator a question, and the inbox.

Record status per STATUS.md at the end of every step; in step 6 `start`, `land`, `halt` and `finish` write it themselves. Read the inbox per STATUS.md before each step; within step 6 `frontier` and `integrate` read it themselves and exit 5 while notes wait: act on them, then run the command again.

Communicate with subagents through context pointers: issue numbers, worktree paths, research notes, the `drive-spec verify` command. Everything else they read themselves.

An interim notification from a background subagent gets a one-line status; act on its final report.

## Steps

1. **Resolve the run.** For each of `baseBranch`, `bootstrap`, `verify`, `parallel`, `maxSlices`, `localOnly`: a flag wins, then `.claude/drive-spec.json` in the repo root, then the default. Defaults: repository default branch, no bootstrap, verify gate read from the repo's `CLAUDE.md` or `AGENTS.md`, parallel, no ceiling, no local-only slices. `--sequential` sets `parallel` to false. Resolve the worktree root per WORKTREES.md. A cloud session is one where `CLAUDE_CODE_REMOTE` is `true`. Pin the resolved gate with `drive-spec gate <spec> '<verify>'`, wherever it came from: every verdict in the run comes from `drive-spec verify`, which runs the pinned gate and only that gate, and pinning marks the run's start, from which `maxSlices` counts landings. Done when every value is printed with where it came from.

   `localOnly` marks slices only the developer's machine can prove, such as tests that need a desktop app: `label` names them, and `proof` is a file in the repo saying how to prove one beyond the verify gate. In a cloud session these slices are **held**: never built, and anything they block waits. Locally they build one at a time, and their implementer also follows `proof`.

2. **Guard the spec.** Run `drive-spec plan <spec>`, the script beside this file. It discovers the tracer-bullets and their blockers, orders them, and gives each slice's state: `closed`, `open-pr`, `in-flight`, `todo` or `held`. Exit 2 refuses the spec, with the reason on its `refuse:` line: run `drive-spec finish <spec> refused`, and stop. Done when the plan is printed. Whenever a later step needs slice states again, run `drive-spec plan <spec> --json` rather than re-deriving them.

3. **Open the spec worktree.** Branch `agent/local-spec-<n>-<slug>` — the `local-` segment is load-bearing: a repo whose CI advances specs off merges into `agent/spec-*` would otherwise dispatch the next slice itself on every merge here and build it twice. Reuse it from origin when it exists, that is a resume; else cut it from `origin/<base>` and push it. Add the worktree and run bootstrap per WORKTREES.md. Done when the worktree is on the spec branch at origin's HEAD.

4. **Preview.** Print base, spec branch, worktree root, mode, ceiling, and the plan from step 2. Post or refresh the progress comment with `drive-spec progress <spec>` once the spec branch exists. With `--dry-run`, stop here.

5. **Explore.** One general-purpose subagent in the spec worktree reads the spec and every slice not yet closed, explores the code and external docs they touch, and writes notes into the notes directory per WORKTREES.md: `shared.md` for what several slices need, `issue-<m>.md` for each slice. Notes name files, seams, existing patterns to follow, and doc links; they leave the design to the implementer. A slice whose notes file already exists is skipped, so a resume explores only what is new. The subagent also checks every open slice against the spec and against each other, on every run, and writes `conflicts.md` fresh: each place two issues ask for opposite behaviour, naming both issues and quoting both lines. Done when every open slice has a notes file and `conflicts.md` exists. A non-empty `conflicts.md` halts the run before any build: `drive-spec finish <spec> conflicts` posts its list, and stop; the operator settles each conflict in the issues and resumes.

6. **Build the frontier.** Repeat until every slice is closed, the ceiling is reached, or only held slices and the slices they block remain:
   - Pick: `drive-spec frontier <spec> --running <m>,…`, naming the slices whose implementer is running now (`--sequential`, `--max` as resolved in step 1). Each line is an action: `build` or `continue` a slice, or `integrate` one whose PR is already open. It applies the mode, the ceiling, held slices, and one `localOnly` slice at a time. `wait` means let a running implementer finish; `stop:` ends the loop. Exit 2: a slice carries `agent:blocked`; finish the run as halted.
   - For each `build`, `continue` or `integrate`: `drive-spec start <spec> <m>` restores or opens its worktree, bootstraps it, labels it `agent:in-progress`, and prints the implementer brief filled in. Hand that brief, unchanged, to an implementer subagent, in the background when parallel. An `integrate` slice goes straight to the integration queue. The implementer is done when every change is committed and `drive-spec verify` is green on that HEAD. Completed slices enter the integration queue in finish order.
   - Integrate one slice at a time: `drive-spec integrate <spec> <m> --deviations -`, the implementer's `Deviations:` list on stdin. It opens the slice PR, merges the latest spec branch into the slice, verifies that exact integration, pushes, and merges the PR at the verified HEAD, again whenever the spec branch moves. Exit 3 is a conflict: a merger subagent in the slice worktree runs the `git merge` it names, resolves and commits, then integrate again. Exit 4 is red. Exit 2 refuses and says why: fix that, never route around it.
   - Land: `drive-spec land <spec> <m>`. It closes the issue naming the PR, removes the slice worktree and branches, opens the draft spec PR at the first landing, refreshes the progress comment, and writes status. Only then integrate the next completed slice.
   - A slice whose implementation or integration reports red halts the run: `drive-spec halt <spec> <m> <why>`. Every later slice assumes this one landed.
   - `stop: ceiling`: `drive-spec finish <spec> ceiling`. `stop: held`: `drive-spec finish <spec> held`. `stop: done`: go to step 7.

7. **Review the whole.** With every slice closed, run `/code-review` on the spec branch against base. One implementer subagent in the spec worktree fixes every finding; `drive-spec verify <spec> <spec worktree>` green; push. A Spec finding that something is missing or built differently is a finding for the fixer, the same as a Standards one: the spec already decided it. Then run `/code-review` again on the result. Done when a review raises nothing new; after a third review that still does, list what is left in the spec PR body.

8. **Confirm the spec PR.** The draft (TRACKER.md) opened at the first landing stays draft; open it now if absent. With every slice closed, its body's `Ref #<spec>` becomes `Closes #<spec>`, and it lists every deviation the slices reported. `drive-spec progress <spec>`.

9. **Clean up.** Remove the spec worktree, any slice worktree still present, and the notes directory; prune, and print the PR URL. The spec branch stays on origin until the PR merges.

10. **Review and fix the spec PR.** Run `/review-fix-pr <pr>` on the spec PR. It runs after step 9 because it opens the PR head in a worktree of its own and refuses a head checked out elsewhere. The PR stays draft. A run whose PR already carries a `review-fix-pr done` comment newer than the spec branch's last push skips this step. Its fix pass going red halts the run: `drive-spec finish <spec> halted --why '<why>' --step review-pr --resume '/review-fix-pr <pr>'`. Done when its status comment is on the PR; then `drive-spec finish <spec> done`.

Every run ends with `drive-spec finish` or `drive-spec halt`, never both, and only `--dry-run` without either: they post the status comment the operator is notified by, and write the final status. `finish` refuses an outcome the tracker contradicts, such as `done` with a slice still open.
