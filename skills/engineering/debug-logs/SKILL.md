---
name: debug-logs
description: "Stop guessing and instrument the code instead. Self-invoke when: (1) 3+ failed fix attempts on the same bug, (2) about to make a low-confidence guess, or (3) the same assumption has been made multiple times without verification. User can also invoke manually with /debug-logs."
---

# Debug Logs

When debugging stalls — through repeated failed fixes, unverifiable assumptions, or blind guessing — stop attempting fixes and instrument the code to surface real data instead.

## Step 1 — List unknowns

Identify everything you have been assuming rather than knowing. Be explicit:

- What values are you guessing at?
- What execution paths are you assuming are taken?
- What state are you assuming exists at the point of failure?

Present this as a numbered list. Do not proceed until the unknowns are written out.

## Step 2 — Propose a logging plan

For each unknown, propose exactly where to add a log and what to capture. Keep it targeted — one log per unknown, placed as close to the assumption as possible.

Before writing any code:
- Detect the language and grep for the existing logging pattern in the file or project (e.g. `console.log`, `print`, `logger.debug`, `os.log`). Match it exactly. Introduce no new dependencies.

Present the plan as a table:

| # | Unknown | File | Line / location | What to log |
|---|---------|------|-----------------|-------------|

**Wait for approval before touching any code.**

## Step 3 — Add the logs

After approval, add the logs exactly as planned. Match the existing logging style. Add a short inline comment marking each one as `[debug]` so they're easy to find and remove later.

## Step 4 — Give the exact command to run

Tell the user exactly what to run to reproduce the bug with the logs active. One command, copy-pasteable. If environment variables or flags are needed, include them.

Ask the user to paste back the full output.

## Step 5 — Interpret and report

When the output arrives:

1. State what each log line reveals about the unknowns from Step 1.
2. If the data is conclusive: state your conclusion clearly, then propose a fix. **Wait for approval before applying it.**
3. If the data is inconclusive: explain what was learned and what is still unknown. Propose a second, more targeted logging round (return to Step 2). **Wait for approval before continuing.**

## Step 6 — Apply the fix

After fix approval, apply it. Then ask the user to confirm the fix works before proceeding.

**Do not remove the debug logs until the user confirms the fix is working.**

## Step 7 — Clean up

After the user confirms the fix works, remove all `[debug]` log lines. Verify no debug instrumentation remains.
