# drive-spec-view

One drive-spec run at a glance: its step, state and question, and each slice with the agent building it. It's read-only. It comes two ways: a Claude Code mod, for any session including cloud sessions, and a Rex pane, `rex/drive_spec_view.py`, a terminal program using only the Python 3 standard library.

## Mod

- `/drive-spec-view` opens the pane, or closes it. `/drive-spec-view <spec>` shows that spec; `/drive-spec-view follow` goes back to following.
- **Opens on its own** once per session, when a run whose status file names this session appears: the web app holds a typed command until the turn ends. Closed, it stays closed. Not in a Rex pane (`REX_BLOCK` set): there, alt+cmd+r shows the run in the Rex pane.
- **Which run**, first match wins: the spec picked with `/drive-spec-view <spec>` or in the list; the run whose status file names this session in `session_id`; the repo's only `running` or `waiting` run. With none, the pane lists the repo's runs, waiting first, each a button that shows it.
- **Status line:** while a run is picked, the session's status line reads `drive-spec #<n> · <state> · <step> <i>/11 · <landed>/<total> landed`, with `▲ waiting on you` while a blocking question waits. It shows with the pane closed.
- **Pane:** the spec and why it is shown, then cards for the question, the run (state, step, `updated … ago`, red once a `running` run is quiet for 10 minutes, summary, next), the 11 steps, progress (landed bar, spec PR, base, branch) and one card per slice. Slice states, glyphs and agent rows are the Rex pane's below. Issue and PR numbers are links.
- **Refresh:** the status files every 2 seconds, from `$GIT_COMMON_DIR/drive-spec/status/` of the session's folder. The plan comes from `drive-spec plan <spec> --json` every 60 seconds, with the script from `~/.claude-on/skills` or `~/.claude/skills`. Once every slice is closed it is read only on `↻ refresh`, and after a failed read the next waits 10 minutes. The pane's model and the status line are written only when they change, with ages at the precision they show (seconds under a minute, whole minutes after): each write is an event in the session's stream, and a cloud session keeps every one.
- **Cloud sessions:** `scripts/cloud-setup.sh` copies the mod to `~/.claude/mods/` and names it in `CLAUDE_CODE_PLUGIN_DIRS`. Locally, add this folder to `CLAUDE_CODE_PLUGIN_DIRS` in the `env` of `settings.json`.

```sh
claude plugin validate mods/drive-spec-view
claude plugin test mods/drive-spec-view
```

## Rex pane


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
  - **Slices:** one card per slice, in build order from `drive-spec plan <spec> --json`, run every 60 seconds and on `r`. Once every slice is closed the plan cannot change, so it is read once and then only on `r`: after cleanup each read lists every issue in the repo. After a failed read, such as GitHub's rate limit, the next waits 10 minutes. Each card is coloured by the slice's state, with its glyph and number in the top border and its state at the right: `✓` landed (with when, from `landed.jsonl`), `●` building, `⇄` merging, `◷` queued to integrate, `✗` halted (`agent:blocked`), `⏸` held, `◆` open PR, `◇` in flight, `○` todo with `after #…` for open blockers. The title wraps over up to 3 lines. A slice with an agent in the status file's `agents` map also shows the agent's role, the time since it started, and its last tool call from its log. The card is flagged `⚠ quiet` once the log has been silent for 5 minutes.
- **Refresh:** the status file and logs are read every 2 seconds, dispatch every 10. After cleanup the logs are gone, so agent rows go, but the slices still come from the plan.
- **Keys:** `↑↓`/`jk` or the wheel scroll, `⏎`/`o` open the spec PR (the spec issue before there is one), `l` tail the running agent's log in a split below (with several running, it asks which by number), `g` show the run's own Rex tab, `s` picker, `r` refresh, `q` close. Nothing in the run view is selected: a click on a `#` opens that issue or PR, and a click on an agent's `▸ log` tails its log.
- It reads only the machine it runs on: in a session on a remote host, it opens there and shows that host's runs.

The Rex server reads `init.lua` on its own machine, so add the action on each machine whose Rex server should have it, and run the reload there: `rex -S <host> config reload` is refused.

```sh
echo 'dofile(os.getenv("HOME") .. "/Development/skills/mods/drive-spec-view/rex/drive_spec_view.lua")' >> ~/.config/rex/init.lua
rex config reload
```

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s mods/drive-spec-view/rex
```
