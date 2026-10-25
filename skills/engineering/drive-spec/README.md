# drive-spec

Skill: builds a spec's tracer-bullet issues, each in its own worktree, into one draft PR. Entry point is [`SKILL.md`](SKILL.md).

## The `drive-spec` script

Python 3, standard library only, with `gh` and `git` on the PATH. Run it from inside the repo. It holds the run's deterministic rules, so the model calls them rather than remembers them.

- `drive-spec plan <spec> [--json]`: the spec's slices in build order, each with its state, blockers, branch and PR. Read-only, except that without `--json`, once `gate` has written `guard`, it writes `worktree` as begun; outside a run it writes nothing. Exit 2 refuses the spec (a `## Parent` of its own, no tracer-bullets, a cycle), with the reason on the `refuse:` line; exit 1 is a failed tracker or git call. Contract: [`TRACKER.md`](TRACKER.md), Discovery.
- `drive-spec gate <spec> [<command> [--base <branch>]]`: prints the run's verify gate, or pins one for the run (pinned wins over `verify` in `.claude/drive-spec.json`), marking the run's start and writing `base` to the status file.
- `drive-spec verify <spec>|pr-<n> <worktree> [--gate <command>] [--wait-minutes N]`: runs the gate on a clean worktree's HEAD, one at a time under the host-wide lock (`DRIVE_SPEC_VERIFY_LOCK`, default `/tmp/drive-spec-verify.lock`; a wait names the holder), and records the verdict against that commit. One run per commit: a claim under `running/<sha>.json` makes a second call attach to the run already going, and a new commit in the same worktree waits out the gate on the old one. With `--wait-minutes`, the gate runs detached and the call returns exit 6 once the minutes pass; the same command again attaches and waits on. Without it, the gate runs in the call, and killing the call stops it. The gate runs in a process group of its own: past `verifyTimeoutMinutes` (default 60) it is stopped whole and red. Exit 4 when red, with the log's tail. A commit already green under the same gate is not run again, nor is one with the very tree of a green commit (a merge commit GitHub made from a verified head); a verdict from another gate counts for nothing. `pr-<n>` is `/review-fix-pr`'s form, with its verdicts under `$GIT_COMMON_DIR/drive-spec/pr-<n>/`; `--gate` goes with it only, never with a spec. `land` and `cleanup` find what still runs in a worktree through `/proc`, or `ps` and `lsof` on macOS.
- `drive-spec integrate <spec> <m> [--deviations <text>|-] [--wait-minutes N]`: opens the slice PR, merges the spec branch in, verifies, pushes, and merges the PR at the verified SHA, looping while the spec branch moves. Exit 3 on a conflict, 4 when red, 6 when the wait ran out with a gate still running: the same command again picks up where it stopped.
- `drive-spec land <spec> <m>`: closes a merged slice, stops any gate still running in its worktree (and names any other process left there), removes the worktree and branches, opens the draft spec PR at the first landing, refreshes the progress comment, writes status. Safe to run again.
- `drive-spec progress <spec>`: posts or refreshes the progress comment.
- `drive-spec open <spec> [--base <branch>]`: the spec worktree, reused, resumed from origin, or cut from `origin/<base>` and pushed; bootstraps it until a bootstrap succeeds (WORKTREES.md, Bootstrap); writes `branch` and `base` to the status file. Contract: [`WORKTREES.md`](WORKTREES.md), Create.
- `drive-spec explore <spec>`: writes the explorer brief, [`EXPLORER.md`](EXPLORER.md) filled, to `brief-explore.md`.
- `drive-spec preview <spec> [--sequential] [--max N] [--dry-run]`: prints the run and the plan, refreshes the progress comment; `--dry-run` writes `paused`.
- `drive-spec explored <spec>`: refuses until every open slice has notes and `conflicts.md`, `coverage.md` and `questions.md` are fresh this run, while `coverage.md` holds a line out of form, a slice not of this spec, or an `unmapped` requirement, and while a `questions.md` id has no `[Q<k>]` answer in `decisions.md`; exit 3 when it lists conflicts, after finishing the run as `conflicts`.
- `drive-spec review <spec>`: step 7, one call per move. With every slice closed and the spec worktree clean and green (a green HEAD ahead of origin is pushed), it writes the next round's reviewer brief ([`REVIEWER.md`](REVIEWER.md)); once the round's findings file is in, it holds the file to its form and writes a fixer brief ([`REVIEW-FIXER.md`](REVIEW-FIXER.md)) of its rule findings, or prints `review clean`. Past `reviewRounds` (default 3) with rule findings open, it refuses until the operator has answered since the last round.
- `drive-spec reviewed <spec> [--left <text>|-]`: refuses until the last round is a clean review of the pushed, green HEAD; keeps every round's judgement calls, and `--left`, for `confirm`.
- `drive-spec next <spec>`: the command that carries the run on, read from its status file.
- `drive-spec confirm <spec> [--left <text>|-]`: with every slice closed, rewrites the draft spec PR's body to `Closes #<spec>`, the slices, the deviations from their PRs, and what review left; opens the draft first when absent.
- `drive-spec cleanup <spec>`: with every slice closed and nothing unpushed in the spec worktree, stops any process still running in the spec and slice worktrees, removes them and the notes directory, and prints the spec PR URL.
- `drive-spec frontier <spec> [--running <m>,…] [--sequential] [--max N] [--json]`: what to do next, one line per slice (`build`, `continue`, `integrate`), or `wait`, or `stop: done|ceiling|held`. Read-only, except that `stop: done` while the status reads `build` writes `review` as begun. Mode and ceiling default from `.claude/drive-spec.json`; the ceiling counts landings since the gate was pinned. Exit 2 when a slice carries `agent:blocked`.
- `drive-spec start <spec> <m>`: for a slice on the frontier, restores its worktree (an existing one, the local branch, or the branch on origin) or opens it fresh from the spec branch HEAD; bootstraps it until a bootstrap succeeds; labels it `agent:in-progress`; writes the filled [`IMPLEMENTER.md`](IMPLEMENTER.md) brief to `brief-<m>.md` and prints the prompt that points at it.
- `drive-spec halt <spec> <m> <why>`: blocks the slice, comments on it, and finishes the run as halted.
- `drive-spec ask <spec> <question> [--no-block] [--step] [--ref Q<k>,…]`: writes the question to the status file, `waiting` unless `--no-block`; `--ref` names the `questions.md` ids it settles, and `answered` records them in `decisions.md`.
- `drive-spec answered <spec> <answer>|-`: posts the operator's decision on the spec, appends it to `decisions.md` for the implementer briefs, clears the question.
- `drive-spec finish <spec> done|halted|conflicts|ceiling|held|refused [--why] [--slice] [--step] [--resume] [--left]`: posts the status comment, refreshes the progress comment, writes the final status with `branch` and `pr_url`. With done, what review left comes from the spec PR body, or `--left`. Refuses an outcome the tracker contradicts.

Exit codes: 0 done, 1 a failed call, 2 refused (a rule would break; the message names it), 3 conflict, 4 red, 6 a gate still running (run the same command again), 5 inbox notes to act on first (`open`, `preview`, `frontier`, `integrate`, `confirm`, `cleanup`). Contracts: [`TRACKER.md`](TRACKER.md).

State, all under `$GIT_COMMON_DIR/drive-spec/spec-<n>/`, removed with the notes in step 9: `gate` (the pinned gate), `run.json` (when it was pinned: the run's start), `issues.json` (the tracker cache: the first call lists every issue, later ones only those updated since), `landed.jsonl` (each landing), `brief-*.md` (the subagent briefs), `coverage.md`, `questions.md`, `question-ref`, `review/round-<k>.{meta.json,brief.md,json,fix.md}`, `left.md` (what review left), `decisions.md` (the operator's answers), `verified/<sha>.json` and `verified/tree-<tree>.json` (each verdict), `running/<sha>.json` (the claim of a gate run in progress), `logs/<sha>.log`, `logs/bootstrap-<worktree>.log`, `integrate.lock`.

Tests: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/engineering/drive-spec`, from the repo root. They run the pure logic on fixtures; the script end to end with real git against a bare origin and a fake `gh` that answers through real `jq`; and the real `dispatch` on the status files the script writes, against the steps and states in [`STATUS.md`](STATUS.md).

## status.sh

Writes the run's status file so a dispatcher can watch every drive-spec on the machine without reading transcripts. Contract and states: [`STATUS.md`](STATUS.md).

- State: `$GIT_COMMON_DIR/drive-spec/status/spec-<n>.json`, one file per spec, written only by that spec's run. It sits inside the repo's shared `.git` dir, so every worktree sees it, nothing commits it, and step 9's cleanup leaves it in place.
- Safe without a reader: it always exits 0, and a failed write only prints a warning.
- Needs `git` and `jq`; without `jq` it skips the write.
- `status.sh <n> --touch` refreshes only `updated_at`: `verify`'s heartbeat.
- `status.sh <n> --inbox` prints the dispatcher's unread notes from `spec-<n>.inbox.md` and moves them to `spec-<n>.inbox-read.md`.

```sh
./status.sh 2983 step=build state=running summary="landed 2/5; building #2990" next="integrate #2990"
```
