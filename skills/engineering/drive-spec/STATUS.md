# Status

One JSON file per spec, read by a dispatcher that watches every run on the machine without reading transcripts. Each write replaces the run's whole picture: the reader sees only this file, so `summary` and `next` stand alone.

```sh
<skill dir>/status.sh <spec> step=<step> state=<state> summary="<one line>" next="<one line>" [base=…] [branch=…] [pr_url=…] [question="…" question_blocking=true|false]
```

`status.sh` sits beside this file. It writes `$GIT_COMMON_DIR/drive-spec/status/spec-<spec>.json` atomically, merges into the previous write, stamps `updated_at`, `repo`, `host`, `session_id`, `config_dir` (the session's Claude config dir, where the dispatcher looks the session up), `pane` and `mux` itself, and always exits 0: a status write never stops the run. Each write and `--touch` holds an flock on `.spec-<spec>.lock` beside the file while it reads, rewrites and renames it, so a heartbeat from another process never puts back a map `build` just replaced. `key=` with an empty value clears that key. `pane` is the multiplexer pane the run writes from: `HERDR_PANE_ID` with `mux` `herdr`, else `REX_BLOCK` with `mux` `rex`; with neither set, the previous pair stays. A file written before `pane` existed holds `herdr_pane` instead, which the dispatcher still reads as a herdr pane; the next write with a pane replaces it.

## When

At every step boundary, and within step 6 at each agent launch, landing and halt. `step` is the step in progress: the command that ends one step writes the next as begun, with a `summary` of what just finished, so a long stretch of model work (exploring, implementers, review rounds) reads as its own step while it runs. The `drive-spec` commands write it, never the model; this table is their contract, and `test_drive_spec.py` holds them to it and runs the real dispatcher on what they write. Every write carries `step`, `state`, `summary` and `next`, except three partial writes; `base` from step 1, `branch` from step 3, and `pr_url` once the spec PR exists. The partial writes: `build`'s `agents` map (Agents), which replaces the map alone; `drive-spec ask --no-block`, which writes `step`, `question` and `question_blocking`; and the `--touch` heartbeat, which refreshes `updated_at` alone. Every key a partial write leaves out stays as the last full write left it.

| Step in progress | Written by |
|---|---|
| `resolve` | nothing before `gate`; only `drive-spec ask` at step 1 |
| `guard` | `drive-spec gate <spec> '<verify>' --base <base>`; refused: `finish refused` |
| `worktree` | `drive-spec plan <spec>`, only once `gate` has written `guard`, so a plan read outside a run writes nothing |
| `preview` | `drive-spec open` |
| `explore` | `drive-spec preview` (`paused` at `preview` with `--dry-run`); conflicts: `finish conflicts` |
| `build` | `explored`, `start`, `build`, `land`, `halt`, `finish ceiling\|held` |
| `review` | `land` of the last slice, or `frontier` as it stops on `done` while the status still reads `build`; then `drive-spec review` at each round, fix and clean |
| `confirm` | `drive-spec reviewed` |
| `cleanup` | `drive-spec confirm` |
| `review-pr` | `drive-spec cleanup`; `finish halted --step review-pr` |
| `qa-pr` | `drive-spec qa`; `finish done`, or `finish halted --step qa-pr` |
| any, `waiting` | `drive-spec ask`; `drive-spec answered` sets it `running` again |

`step` is the step's name: `resolve`, `guard`, `worktree`, `preview`, `explore`, `build`, `review`, `confirm`, `cleanup`, `review-pr`, `qa-pr`.

While a gate runs or waits for the host-wide lock, `drive-spec verify` refreshes `updated_at` every 5 minutes (`status.sh <spec> --touch`), so a run idle on a background gate never reads as stalled; `pr-<n>` refreshes the running spec whose `pr_url` is that PR.

| `state` | When | `next` |
|---|---|---|
| `running` | the run is working | what it does next |
| `waiting` | the run has stopped for the operator's answer | what it does once answered |
| `halted` | a slice went red, step 2 refused the spec, step 10's fix pass went red, or step 11 failed a scenario | the resume command |
| `paused` | `maxSlices`, only held slices left, or `--dry-run` | the resume command |
| `done` | step 11 posted its QA comment with no failed scenario | `none` |

`summary` in step 6 counts progress: `landed 3/7; building #2990, #2991`.

## Agents

`drive-spec build` keeps an `agents` map in the status file: one entry per slice with an agent running for it or waiting in the integration queue, keyed by the slice number as a string, removed once that slice lands or halts. Every key counts as running when `build` asks `frontier`.

```json
"agents": {"2990": {"role": "implementer", "pid": 4242, "log": "<notes>/logs/agent-2990-implementer.log", "session_id": "…", "started_at": "2026-11-03T09:12:00+00:00"}}
```

`role` is `implementer`; `merger` for the agent `build` launched on an integrate conflict, in place of the slice's queue entry, which also holds `target`, the spec branch SHA it merges, and the slice's `finished_at`, so it keeps its place in the queue; or `integrate` for a slice `frontier` printed as `integrate`, whose PR was already open: it has no agent, only `pr`, `report: null` and `finished_at`, and is integrated without a report. `pid` is the agent's process, detached in a session of its own. `log` is its stream, appended to on each launch: watch it to follow the slice live. `session_id` is the agent's session, read from the stream once it names it, `null` until then. `started_at` is when `build` launched it. `merged: true` marks a queue entry whose PR has merged: the next pass runs only `land` on it. `build` writes the whole map with `status.sh <spec> agents='<JSON>'`, and writes it again while it waits if another write dropped it.

The map is how a `build` resumes another's work. On entry, and on each pass, `build` reads it and treats each entry by what it finds:

- **Live.** The PID runs and its command still names the slice's brief (the merger's for a merger), so a reused PID is not mistaken for it: `build` adopts the agent and waits for it. It never launches a second agent on that slice.
- **Reported.** A `report` key holds the validated report in `integrate`'s `--report` text form, and `finished_at` the last write to the agent's log: the slice waits for, or is part way through, `integrate`, which the next pass runs again. The queue is integrated one slice at a time in `finished_at` order, each landed before the next. A merger still at work holds the queue, so the slices behind it keep their order. The report is read once.
- **Finished, report missing or malformed.** `build` resumes the session once through `agentResume`, asking for the report block only: the entry gains `resumed: true`, with the new PID, and the resumed run appends to the same log. Still missing or malformed after that, the slice halts.
- **Died.** The PID is gone and the log's last run has no `result` event: the agent ended without a response. `build` restarts it once, through `start` on the same worktree and branch, so its commits are kept and the brief says to carry on; the entry gains `restarts: 1`, with the new PID. A second death halts the slice.

`build --wait-minutes N` returns exit 6 once N minutes pass with an agent still running, leaving the map as it is; so does a `build` stopped by a signal or a session ending. The next `build` adopts what it finds.

## Questions

When the run needs the operator's decision to go on, ask it and end the turn:

```sh
drive-spec ask <spec> "<the question, with the options and your recommendation>"
```

It writes `state=waiting` with the question, blocking, at the current step. One question waits at a time, and `ask` refuses another until it is answered: put every decision the run needs now into one question. The question is read on a phone with no other context: name the issue, the choice, and what each answer leads to. The answer arrives as the next prompt; record it before acting on it:

```sh
drive-spec answered <spec> "<the operator's words>"
```

It posts the decision to the spec as a comment, appends it to `decisions.md` in the notes directory, where every later implementer brief points, clears the question, and sets `state=running`.

A judgement call the run made on its own and the operator may want to revisit is a non-blocking question: `drive-spec ask <spec> "<…>" --no-block`, and the run goes on.

## Inbox

The dispatcher leaves notes for the run in an inbox beside the status file. The run reads it at a **boundary** only, never mid-step, and only once the spec branch exists: the end of `drive-spec open` (step 3), then the start of `preview`, `frontier` (before every pick, and before step 7), each pass of `build`, `integrate`, `confirm` and `cleanup`. Each reads it itself: with notes waiting, it prints them and exits 5, and runs again once the notes are handled. Notes that arrive before step 3 wait in the inbox for `open`; notes that arrive during steps 10 and 11 stay unread; once the run is `done`, the dispatcher stops writing notes and alerts the operator itself when base touches files the draft PR changes (from `branch`).

```sh
<skill dir>/status.sh <spec> --inbox
```

Prints any unread notes and archives them; prints nothing when the inbox is empty.

A **base note** starts `## <base> advanced:` and names what landed in base, the files it changed, and an `Overlaps your branch:` line: the files the spec branch changes too.

- Overlap listed: at this boundary, merge `origin/<base>` into the spec branch in the spec worktree. A conflict goes to a merger subagent in the spec worktree, pointed at the conflicted files and the `git merge` to run; then `drive-spec verify <spec> <spec worktree>`, then push. Slices dispatched afterwards start from the merged branch; slices already in flight take it up at integration.
- `Overlaps your branch: unknown`: base moved before the spec branch reached origin, and `open` cut it from the newer base: nothing to merge.

Say in the next `summary` what the note led to: `merged develop (#2998)` or `develop #2998: nothing to merge`. A base commit that shares no file with the spec branch leaves no note.
