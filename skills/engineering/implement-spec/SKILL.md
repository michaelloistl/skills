---
name: implement-spec
description: "Build a spec's tracer-bullets, each in its own worktree, into one draft PR."
disable-model-invocation: true
---

# implement-spec

`/implement-spec <spec-issue> [--base <branch>] [--parallel] [--dry-run]`

Drive a spec issue from its tracer-bullet issues to one draft PR `spec branch → base`. Each slice is built in its own worktree and merged into the spec branch, which lives in a worktree of its own. The checkout you are standing in is never touched, so several sessions can drive several specs in one repo at once.

The tickets are a task graph. Slices whose blockers have all closed form the **frontier**. State lives only in the tracker and the branches, so any session can resume any spec, and the same slice never builds twice.

Reference, read when a step points at it:

- [`TRACKER.md`](TRACKER.md) — discovery, blockers, labels, the progress comment, PRs.
- [`WORKTREES.md`](WORKTREES.md) — root, naming, create, bootstrap, resume rules, cleanup.
- [`IMPLEMENTER.md`](IMPLEMENTER.md) — the brief handed to each implementer subagent.

Communicate with subagents through context pointers: issue numbers, worktree paths, the verify gate. Everything else they read themselves.

## Steps

1. **Resolve the run.** For each of `baseBranch`, `bootstrap`, `verify`, `parallel`, `maxSlices`: a flag wins, then `.claude/implement-spec.json` in the repo root, then the default. Defaults: repository default branch, no bootstrap, verify gate read from the repo's `CLAUDE.md` or `AGENTS.md`, sequential, no ceiling. Resolve the worktree root per WORKTREES.md. Done when every value is printed with where it came from.

2. **Guard the spec.** Discover the spec's tracer-bullets and each one's blockers per TRACKER.md. Refuse when the spec has a `## Parent` of its own, has no tracer-bullets, or the blockers form a cycle: comment on the spec naming the offending issue, and stop. Done when the topological order is computed, lowest issue number first among ties, with each slice's state (closed, open PR, in-flight branch, todo).

3. **Open the spec worktree.** Branch `agent/local-spec-<n>-<slug>` — the `local-` segment is load-bearing: a repo whose CI advances specs off merges into `agent/spec-*` would otherwise dispatch the next slice itself on every merge here and build it twice. Reuse it from origin when it exists, that is a resume; else cut it from `origin/<base>` and push it. Add the worktree and run bootstrap per WORKTREES.md. Done when the worktree is on the spec branch at origin's HEAD.

4. **Preview.** Print base, spec branch, worktree root, mode, ceiling, and the order with each slice's state. Post or refresh the progress comment per TRACKER.md. With `--dry-run`, stop here.

5. **Build the frontier.** Repeat until every slice is closed or the ceiling is reached:
   - Pick from the frontier: open slices whose blockers are all closed. Sequential: the lowest-numbered one. Parallel: all of them, each in a background subagent; completed slices enter the integration queue in finish order.
   - A slice with an open PR into the spec branch gets its worktree back and goes straight to the integration queue. A slice with an in-flight branch on origin gets its worktree back and its implementer told to continue.
   - Otherwise open its worktree on `agent/issue-<m>-<slug>` from the spec branch HEAD, run bootstrap, label the issue `agent:in-progress`, and dispatch an implementer subagent with IMPLEMENTER.md filled in. The subagent is done when the verify gate is green and every change is committed.
   - Integrate one slice at a time per TRACKER.md: push and open its PR, merge the latest spec branch into the slice, resolve conflicts, run the verify gate on that exact integration, push, then merge the PR. If the spec branch advances before the PR merges, integrate and verify again. GitHub's initial mergeable result never substitutes for this gate.
   - Land: confirm the PR merged, pull the spec worktree, close the issue naming the PR, remove the slice worktree and branch, refresh the progress comment. Only then integrate the next completed slice.
   - A slice whose implementation or integration reports red halts the run: label it `agent:blocked`, comment why, print the resume command. Every later slice assumes this one landed.
   - At `maxSlices`, stop cleanly and print the resume command.

6. **Review the whole.** With every slice closed, run `/code-review` on the spec branch against base. One implementer subagent in the spec worktree fixes every finding; verify gate green; push. Done when the review raises nothing the subagent left standing.

7. **Open the final PR.** Draft, `spec branch → base`, body `Closes #<spec>` and the slice list per TRACKER.md. An open one already there is left as is. Refresh the progress comment.

8. **Clean up.** Remove the spec worktree and any slice worktree still present, prune, and print the PR URL. The spec branch stays on origin until the PR merges.
