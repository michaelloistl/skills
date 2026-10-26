# dispatch

A dispatcher over every drive-spec run on the machine: it watches them, starts new ones, tells them what lands in their base branch, and brings them back after a reboot. `/dispatch` turns one standing session into the operator's single window; [`SKILL.md`](SKILL.md) is its playbook.

## The `dispatch` script

Python 3, standard library only. Run it from inside the repo, or pass `--repo PATH` (repeatable).

- `dispatch status [--json]`: one line per spec, what needs the operator first. A done spec acked since its last change, with no live pane or busy session, is left out; `--json` keeps it, with `"acked": true`.
- `dispatch watch`: prints a line each time a spec starts or stops needing the operator, and nothing else. It wakes on status-file writes (inotify on Linux; on macOS, a once-a-second check of the files' mtimes) and herdr agent-state events (the herdr socket's `events.subscribe`), with a 60-second tick for stalls. Every 2 minutes it also runs `merges`. Starting a watch stops any earlier one, which prints `watch superseded by a newer one: leave this one stopped` and exits;.
- `dispatch ack <spec>`: hides a done spec until its status changes. When it is `done` and its session idle, also closes its herdr tab; the session stays resumable with `claude --resume <session_id>` from its status file.
- `dispatch answer <spec> <text>`: sends the operator's answer to a spec whose status is `waiting` on a blocking question, as a prompt into its pane that quotes the question. It refuses a spec that is not waiting, is still working, or has no pane, so an answer never lands mid-step.
- `dispatch launch <spec>… [--force]`: starts each spec in a new herdr tab `spec-<n>` in the caller's workspace, cwd the repo root, as Claude session `drive-spec-<n>` running `/drive-spec <n>`. drive-spec makes its own worktree and branch. A spec already live is skipped. One whose session sits idle in its own pane, after a halt, a pause or an interruption, is resumed there instead: prompted with the `next` command its status file holds (`/drive-spec <n>`, or `/review-fix-pr <pr>` after a review-pr halt). One waiting on its question, or done, is left alone. Under pressure the spec is queued instead, and `watch` prints `READY` when the head of the queue can start.
- `dispatch admit`: the pressure readings and the verdict a launch would get.
- `dispatch unqueue <spec>`: drops a queued spec.
- `dispatch recover [--do <spec>=resume|restart|leave …]`: without `--do`, proposes an action for each spec whose status says `running` but whose session is not working, plus `leave` for waiting, halted and paused specs. With `--do`, acts: `resume` sends `/drive-spec <n>` to the spec's own session (in its restored pane, or reopened with `claude --resume` in a new tab); `restart` sends it to a fresh session (`/clear` in its pane, or a new tab). drive-spec resumes from the tracker and branches either way.
- `dispatch merges`: fetches each repo's base branch once and handles every first-parent commit since the last fetch. Each unfinished spec whose branch shares files with the commit, or has no branch on origin yet, gets a base note appended to its inbox, naming the PR, its files, and the files it shares with the spec branch; the spec reads it at its next boundary (drive-spec's STATUS.md, Inbox). A done spec whose draft PR overlaps prints `OVERLAP`. A spec whose own PR landed is archived.

A spec is joined across three sources: its status file, its herdr pane (by the pane id in the file, or a pane titled `drive-spec-<n>`), and its Claude session (`claude agents --json`, which still reads `busy` while background subagents run and herdr reads `idle`).

## Admission

A launch queues when any of these holds; each limit has an env override.

| Reading | Limit | Override |
|---|---|---|
| `/proc/pressure/cpu` `some avg60` | > 40 | `DISPATCH_MAX_CPU` |
| `/proc/pressure/memory` `some avg10` | > 5 | `DISPATCH_MAX_MEMORY` |

## State

- Read: `$GIT_COMMON_DIR/drive-spec/status/spec-<n>.json`, written by drive-spec's `status.sh`. Written there: `spec-<n>.inbox.md`, the unread notes, and `archive/` for specs whose PR landed. Contract: [`../drive-spec/STATUS.md`](../drive-spec/STATUS.md).
- Written: `${XDG_STATE_HOME:-~/.local/state}/dispatch/`. `acked.json` holds the acked specs; `queue.json` the queued ones; `reported.json` what `watch` last reported, so a restart reports only what changed; `bases.json` the last base SHA seen per repo. `watch.pid` holds the running watch's pid.

## After a reboot

herdr runs as the user's server and starts when the operator first attaches. On start it restores its workspaces and, with `resume_agents_on_restore` (default on), reopens each Claude pane in its own session, idle. Background subagents, verify gates and the dispatcher's monitor are gone. Run `/dispatch` in the dispatcher pane: it starts with `dispatch recover`.
