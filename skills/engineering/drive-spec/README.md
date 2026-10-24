# drive-spec

Skill: builds a spec's tracer-bullet issues, each in its own worktree, into one draft PR. Entry point is [`SKILL.md`](SKILL.md).

## The `drive-spec` script

Python 3, standard library only, with `gh` and `git` on the PATH. Run it from inside the repo. It holds the run's deterministic rules, so the model calls them rather than remembers them.

- `drive-spec plan <spec> [--json]`: the spec's slices in build order, each with its state, blockers, branch and PR. Read-only. Exit 2 refuses the spec (a `## Parent` of its own, no tracer-bullets, a cycle), with the reason on the `refuse:` line; exit 1 is a failed tracker or git call. Contract: [`TRACKER.md`](TRACKER.md), Discovery.
- `drive-spec gate <spec> [<command>]`: prints the run's verify gate, or pins one for the run (pinned wins over `verify` in `.claude/drive-spec.json`).
- `drive-spec verify <spec> <worktree>`: runs the gate on a clean worktree's HEAD, under the host-wide `flock` when available, and records the verdict against that commit. Exit 4 when red, with the log's tail. A commit already green is not run again.
- `drive-spec integrate <spec> <m> [--deviations <text>|-]`: opens the slice PR, merges the spec branch in, verifies, pushes, and merges the PR at the verified SHA, looping while the spec branch moves. Exit 3 on a conflict, 4 when red.
- `drive-spec land <spec> <m>`: closes a merged slice, removes its worktree and branches, opens the draft spec PR at the first landing, refreshes the progress comment, writes status. Safe to run again.
- `drive-spec progress <spec>`: posts or refreshes the progress comment.
- `drive-spec open <spec> [--base <branch>]`: the spec worktree, reused, resumed from origin, or cut from `origin/<base>` and pushed; bootstraps a new one; writes `branch` and `base` to the status file. Contract: [`WORKTREES.md`](WORKTREES.md), Create.
- `drive-spec confirm <spec> [--left <text>|-]`: with every slice closed, rewrites the draft spec PR's body to `Closes #<spec>`, the slices, and the deviations from their PRs; opens the draft first when absent.
- `drive-spec cleanup <spec>`: with every slice closed and nothing unpushed in the spec worktree, removes the spec and slice worktrees and the notes directory, and prints the spec PR URL.
- `drive-spec frontier <spec> [--running <m>,…] [--sequential] [--max N] [--json]`: what to do next, one line per slice (`build`, `continue`, `integrate`), or `wait`, or `stop: done|ceiling|held`. Read-only. Mode and ceiling default from `.claude/drive-spec.json`; the ceiling counts landings since the gate was pinned. Exit 2 when a slice carries `agent:blocked`.
- `drive-spec start <spec> <m>`: for a slice on the frontier, restores its worktree (an existing one, the local branch, or the branch on origin) or opens it fresh from the spec branch HEAD; bootstraps a new one; labels it `agent:in-progress`; prints the filled [`IMPLEMENTER.md`](IMPLEMENTER.md) brief.
- `drive-spec halt <spec> <m> <why>`: blocks the slice, comments on it, and finishes the run as halted.
- `drive-spec finish <spec> done|halted|conflicts|ceiling|held|refused [--why] [--slice] [--step] [--resume] [--left]`: posts the status comment, refreshes the progress comment, writes the final status with `branch` and `pr_url`. `--left` (done only) lists what the last review left open. Refuses an outcome the tracker contradicts.

Exit codes: 0 done, 1 a failed call, 2 refused (a rule would break; the message names it), 3 conflict, 4 red, 5 inbox notes to act on first (`frontier`, `integrate`). Contracts: [`TRACKER.md`](TRACKER.md).

State, all under `$GIT_COMMON_DIR/drive-spec/spec-<n>/`, removed with the notes in step 9: `gate` (the pinned gate), `run.json` (when it was pinned: the run's start), `landed.jsonl` (each landing), `verified/<sha>.json` (each verdict), `logs/<sha>.log`, `integrate.lock`.

Tests: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/engineering/drive-spec`, from the repo root. They run the pure logic on fixtures; the script end to end with real git against a bare origin and a fake `gh` that answers through real `jq`; and the real `dispatch` on the status files the script writes, against the steps and states in [`STATUS.md`](STATUS.md).

## status.sh

Writes the run's status file so a dispatcher can watch every drive-spec on the machine without reading transcripts. Contract and states: [`STATUS.md`](STATUS.md).

- State: `$GIT_COMMON_DIR/drive-spec/status/spec-<n>.json`, one file per spec, written only by that spec's run. It sits inside the repo's shared `.git` dir, so every worktree sees it, nothing commits it, and step 9's cleanup leaves it in place.
- Safe without a reader: it always exits 0, and a failed write only prints a warning.
- Needs `git` and `jq`; without `jq` it skips the write.
- `status.sh <n> --inbox` prints the dispatcher's unread notes from `spec-<n>.inbox.md` and moves them to `spec-<n>.inbox-read.md`.

```sh
./status.sh 2983 step=build state=running summary="landed 2/5; building #2990" next="integrate #2990"
```
