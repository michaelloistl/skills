# drive-spec-view

A Rex pane showing one drive-spec run: its step, state and question, and each slice with the agent building it. It's read-only. It has no Claude Code mod; `rex/drive_spec_view.py` is a terminal program using only the Python 3 standard library.

- `alt+cmd+r`, or Toggle drive-spec Run in the command palette, opens the view to the right of the focused pane, or closes it. The action is `drive_spec_view` in `rex/drive_spec_view.lua`.
- **Which run:** it follows the pane it opened beside, reading that pane's folder every 5 seconds through the Rex API. The run shown is, first match wins:
  1. the one whose status file names that pane in `pane`
  2. the one `dispatch status --json` matches to that pane, by its `spec-<n>` or `drive-spec-<n>` label or title
  3. the repo's only `running` or `waiting` run
  
  With no match, it shows the picker.
- **Picker:** `s` lists the runs as cards from `dispatch status --json` for the followed repo plus any `--repos`, waiting first, leaving out acked ones. `⏎` shows a run and holds it until `esc`.
- **Layout:** a header, then cards, top to bottom:
  - **Header:** the spec number and title, and which pane it follows.
  - **Question:** a yellow card with the run's question while it waits on one, wrapped whole. A non-blocking note gets a grey card.
  - **Run:** the run's `state`, "step n of 11", `summary` and `next`. The time since `updated_at` sits in the card's border and turns red when a `running` run has been quiet for 10 minutes.
  - **Steps:** the 11 steps as a checklist: `✓` done, `▶` current in its state's colour, `○` to come. Two columns when the pane is wide enough.
  - **Progress:** a landed/total bar across the card, then the spec PR, base and spec branch.
  - **Slices:** one card per slice, in build order from `drive-spec plan <spec> --json`, run every 60 seconds and on `r`. Each card is coloured by the slice's state, with its glyph and number in the top border and its state at the right: `✓` landed (with when, from `landed.jsonl`), `●` building, `⇄` merging, `◷` queued to integrate, `✗` halted (`agent:blocked`), `⏸` held, `◆` open PR, `◇` in flight, `○` todo with `after #…` for open blockers. The title wraps over up to 3 lines. A slice with an agent in the status file's `agents` map also shows the agent's role, the time since it started, and its last tool call from its log. The card is flagged `⚠ quiet` once the log has been silent for 5 minutes. The selected slice is double-bordered.
- **Refresh:** the status file and logs are read every 2 seconds, dispatch every 10. After cleanup the logs are gone, so agent rows go, but the slices still come from the plan.
- **Keys:** `↑↓`/`jk` select a slice, `⏎`/`o` open its PR or issue, `l` tail its agent's log in a split below, `g` show the run's own Rex tab, `s` picker, `r` refresh, `q` close. A click opens a number or selects a slice; the wheel scrolls.
- It reads only its own machine: a devbox's Rex server opens it there, reading the devbox's runs.

Add the action on each Rex server that should have it, then reload:

```sh
echo 'dofile(os.getenv("HOME") .. "/Development/skills/mods/drive-spec-view/rex/drive_spec_view.lua")' >> ~/.config/rex/init.lua
rex config reload
```

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s mods/drive-spec-view/rex
```
