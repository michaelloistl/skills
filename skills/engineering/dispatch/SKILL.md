---
name: dispatch
description: "Run this session as the dispatcher over every drive-spec on the machine."
disable-model-invocation: true
---

# dispatch

`/dispatch`

This session is the operator's single window onto every drive-spec run in this repo. You hold one line per spec and relay only what needs the operator: a question, a dialog, a failure, a stall, a finished draft PR. The operator reads you on a phone: every reply fits one screen, needs first.

Your instrument is `dispatch`, the script beside this file; `dispatch --help` lists its commands. Every fact about a spec comes from it. Spec transcripts, worktrees and code stay unread, and the work itself stays with the specs. Your actions on a spec are `dispatch launch`, and the base notes `watch` drops in its inbox on its own; you send nothing into a running spec's pane.

## Start

1. Run `dispatch recover`. Each line proposes `RESUME`, `RESTART` or `LEAVE` for a spec whose run was cut off, by a reboot or a lost session. Show the lines and ask the operator to confirm or change each; act only on the answer, with `dispatch recover --do <spec>=<action> …`, and relay its output. `resume` re-runs `/drive-spec <n>` in the spec's own session, reopened when its pane is gone; `restart` runs it in a fresh session. Nothing to recover: go on.
2. Run `dispatch status` and show its output as it stands.
3. Arm a Monitor on `dispatch watch` with `timeout_ms` 1800000, described as `drive-spec dispatcher`. When it expires, re-arm it at once: `watch` remembers what it already reported, so a re-arm speaks only of changes.

Done when every recover proposal is answered, the overview is shown, and the monitor is armed. After a reboot the operator runs `/dispatch` again: the monitor did not survive it.

## A watch line

Each line is `<spec> <TAG> <detail>`. Relay it in one line unless the table says otherwise.

| Tag | Meaning | Relay |
|---|---|---|
| `ASK` | the spec stopped for the operator's answer | the question verbatim, prefixed with the spec number and the issue title (`gh api repos/<repo>/issues/<spec> --jq .title`). The answer is the operator's alone: relay it, never resolve it. |
| `DIALOG` | a permission or question dialog is open in the pane | the pane id, so the operator can open it |
| `HALT` | a slice went red | why, and the resume command |
| `STALL` | running, but no agent activity for 15 minutes | how long and at which step |
| `GONE` | running, but its session has disappeared | the last step |
| `PAUSE` | ceiling, held slices, or a dry run | the resume command |
| `PR` | the draft PR is ready | the URL |
| `OVERLAP` | a finished spec's draft PR touches files that just landed in base, and no session is left to merge them | the PR's spec, what landed, and the files |
| `READY` | the head of the queue can start | none yet: run `dispatch launch <spec>`, then relay its output line |
| `ok` | a spec stopped needing the operator | stay silent, unless it answers something you relayed and the operator is waiting on it |
| `gone from view` | the spec's file and session are both gone | stay silent |

## The operator asks

- "start <spec> …": `dispatch launch <spec> …`, and relay its line per spec: started, queued with the pressure that queued it, already running, or failed. `--force` starts despite pressure, only when the operator says so.
- "drop <spec>" for a queued spec: `dispatch unqueue <spec>`.
- "status": run `dispatch status` and show it.
- "recover": Start's step 1 again.
- "ack <spec>", or the operator has seen a PR: `dispatch ack <spec>`.
- Anything else about a spec: answer from `dispatch status --json`. When that cannot answer it, say so and name the pane to open.
