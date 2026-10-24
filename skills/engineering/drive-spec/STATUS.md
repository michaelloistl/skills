# Status

One JSON file per spec, read by a dispatcher that watches every run on the machine without reading transcripts. Each write replaces the run's whole picture: the reader sees only this file, so `summary` and `next` stand alone.

```sh
<skill dir>/status.sh <spec> step=<step> state=<state> summary="<one line>" next="<one line>" [base=…] [branch=…] [pr_url=…] [question="…" question_blocking=true|false]
```

`status.sh` sits beside this file. It writes `$GIT_COMMON_DIR/drive-spec/status/spec-<spec>.json` atomically, merges into the previous write, stamps `updated_at`, `repo`, `host`, `session_id` and `herdr_pane` itself, and always exits 0: a status write never stops the run. `key=` with an empty value clears that key.

## When

At the end of every step, and within step 6 at each dispatch, landing and halt. Every write carries `step`, `state`, `summary` and `next`; add `base` from step 1, `branch` from step 3, and `pr_url` once the spec PR exists.

`step` is the step's name: `resolve`, `guard`, `worktree`, `preview`, `explore`, `build`, `review`, `confirm`, `cleanup`, `review-pr`.

| `state` | When | `next` |
|---|---|---|
| `running` | the run is working | what it does next |
| `waiting` | the run has stopped for the operator's answer | what it does once answered |
| `halted` | a slice went red, step 2 refused the spec, or step 10's fix pass went red | the resume command |
| `paused` | `maxSlices`, only held slices left, or `--dry-run` | the resume command |
| `done` | step 10 posted its status comment | `none` |

`summary` in step 6 counts progress: `landed 3/7; building #2990, #2991`.

## Questions

When the run needs the operator's decision to go on, record it and end the turn:

```sh
status.sh <spec> step=<step> state=waiting question="<the question, with the options and your recommendation>" question_blocking=true summary="…" next="…"
```

The question is read on a phone with no other context: name the issue, the choice, and what each answer leads to. The answer arrives as the next prompt; clear it with `question=` and `state=running` before acting on it.

A judgement call the run made on its own and the operator may want to revisit is a non-blocking question: `question_blocking=false`, `state=running`, and the run goes on.

## Inbox

The dispatcher leaves notes for the run in an inbox beside the status file. The run reads it at a **boundary** only, never mid-step: before each step, and in step 6 before picking from the frontier and before integrating each slice. `drive-spec frontier` and `drive-spec integrate` read it themselves: with notes waiting, they print them and exit 5, and run again once the notes are handled.

```sh
<skill dir>/status.sh <spec> --inbox
```

Prints any unread notes and archives them; prints nothing when the inbox is empty.

A **base note** starts `## <base> advanced:` and names what landed in base, the files it changed, and an `Overlaps your branch:` line: the files the spec branch changes too.

- Overlap listed: at this boundary, merge `origin/<base>` into the spec branch in the spec worktree. Conflicts go to a merger subagent, as in the integration queue; then `drive-spec verify <spec> <spec worktree>`, then push. Slices dispatched afterwards start from the merged branch; slices already in flight take it up at integration. Before step 3 there is no spec branch: carry the note to the first boundary after it. Before step 10 the spec worktree is gone: open it again per WORKTREES.md for the merge, and remove it after the push.
- `Overlaps your branch: none`: nothing to merge.

Either way, say in the next `summary` what the note led to: `merged develop (#2998)` or `develop #2998: no overlap`.
