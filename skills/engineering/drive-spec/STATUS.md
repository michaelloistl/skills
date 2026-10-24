# Status

One JSON file per spec, read by a dispatcher that watches every run on the machine without reading transcripts. Each write replaces the run's whole picture: the reader sees only this file, so `summary` and `next` stand alone.

```sh
<skill dir>/status.sh <spec> step=<step> state=<state> summary="<one line>" next="<one line>" [base=…] [branch=…] [pr_url=…] [question="…" question_blocking=true|false]
```

`status.sh` sits beside this file. It writes `$GIT_COMMON_DIR/drive-spec/status/spec-<spec>.json` atomically, merges into the previous write, stamps `updated_at`, `repo`, `host`, `session_id` and `herdr_pane` itself, and always exits 0: a status write never stops the run. `key=` with an empty value clears that key.

## When

At the end of every step, and within step 6 at each dispatch, landing and halt. The `drive-spec` commands write it, never the model; this table is their contract, and `test_drive_spec.py` holds them to it and runs the real dispatcher on what they write. Every write carries `step`, `state`, `summary` and `next`; `base` from step 1, `branch` from step 3, and `pr_url` once the spec PR exists.

| Step | Written by |
|---|---|
| `resolve` | `drive-spec gate <spec> '<verify>' --base <base>` |
| `guard` | `drive-spec plan <spec>`, only once `gate` has written `resolve`, so a plan read outside a run writes nothing; refused: `finish refused` |
| `worktree` | `drive-spec open` |
| `preview` | `drive-spec preview`; `paused` with `--dry-run` |
| `explore` | `drive-spec explored`; conflicts: `finish conflicts` |
| `build` | `start`, `land`, `halt`, `finish ceiling\|held` |
| `review` | `drive-spec reviewed` |
| `confirm` | `drive-spec confirm` |
| `review-pr` | `drive-spec cleanup` as it starts; `finish done`, or `finish halted --step review-pr` |
| any, `waiting` | `drive-spec ask`; `drive-spec answered` sets it `running` again |

`step` is the step's name: `resolve`, `guard`, `worktree`, `preview`, `explore`, `build`, `review`, `confirm`, `cleanup`, `review-pr`.

While a gate runs or waits for the host-wide lock, `drive-spec verify` refreshes `updated_at` every 5 minutes (`status.sh <spec> --touch`), so a run idle on a background gate never reads as stalled; `pr-<n>` refreshes the running spec whose `pr_url` is that PR.

| `state` | When | `next` |
|---|---|---|
| `running` | the run is working | what it does next |
| `waiting` | the run has stopped for the operator's answer | what it does once answered |
| `halted` | a slice went red, step 2 refused the spec, or step 10's fix pass went red | the resume command |
| `paused` | `maxSlices`, only held slices left, or `--dry-run` | the resume command |
| `done` | step 10 posted its status comment | `none` |

`summary` in step 6 counts progress: `landed 3/7; building #2990, #2991`.

## Questions

When the run needs the operator's decision to go on, ask it and end the turn:

```sh
drive-spec ask <spec> "<the question, with the options and your recommendation>"
```

It writes `state=waiting` with the question, blocking, at the current step. The question is read on a phone with no other context: name the issue, the choice, and what each answer leads to. The answer arrives as the next prompt; record it before acting on it:

```sh
drive-spec answered <spec> "<the operator's words>"
```

It posts the decision to the spec as a comment, appends it to `decisions.md` in the notes directory, where every later implementer brief points, clears the question, and sets `state=running`.

A judgement call the run made on its own and the operator may want to revisit is a non-blocking question: `drive-spec ask <spec> "<…>" --no-block`, and the run goes on.

## Inbox

The dispatcher leaves notes for the run in an inbox beside the status file. The run reads it at a **boundary** only, never mid-step, and only once the spec branch exists: the end of `drive-spec open` (step 3), then the start of `preview`, `frontier` (before every pick, and before step 7), `integrate`, `confirm` and `cleanup`. Each reads it itself: with notes waiting, it prints them and exits 5, and runs again once the notes are handled. Notes that arrive before step 3 wait in the inbox for `open`; notes that arrive during step 10 stay unread; once the run is `done`, the dispatcher stops writing notes and alerts the operator itself when base touches files the draft PR changes (from `branch`).

```sh
<skill dir>/status.sh <spec> --inbox
```

Prints any unread notes and archives them; prints nothing when the inbox is empty.

A **base note** starts `## <base> advanced:` and names what landed in base, the files it changed, and an `Overlaps your branch:` line: the files the spec branch changes too.

- Overlap listed: at this boundary, merge `origin/<base>` into the spec branch in the spec worktree. Conflicts go to a merger subagent, as in the integration queue; then `drive-spec verify <spec> <spec worktree>`, then push. Slices dispatched afterwards start from the merged branch; slices already in flight take it up at integration.
- `Overlaps your branch: none`: nothing to merge.

Either way, say in the next `summary` what the note led to: `merged develop (#2998)` or `develop #2998: no overlap`.
