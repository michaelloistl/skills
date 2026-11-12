# sysmon

A Claude Code mod for a Linux box such as the devbox. It reads `/proc`, so it does nothing useful on macOS.

- **Status line:** CPU and memory, plus a warning when pressure is at or above 10% or disk is at or above 60%.
- **Pane:** `/sysmon` opens the System pane. It shows pressure, CPU and per-core use, memory, swap, disk, load by worktree, process counts against an hour ago, listening ports, Postgres connections, Docker disk use and recent test runs.
- **Shared file:** it writes `~/.local/state/sysmon/groups.json` every 5 seconds, the busiest worktrees.

The mod is loaded through `CLAUDE_CODE_PLUGIN_DIRS` in the `env` block of the devbox's `~/.claude-on/settings.json`.

```sh
claude plugin validate mods/sysmon
```

## Rex pane

`rex/sysmon.py` is a terminal program using only the Python 3 standard library. It reads `/proc`, so it runs in Linux sessions, such as devbox ones. In a Mac session it says so and closes on any key.

- `alt+cmd+s`, or Toggle System Monitor in the command palette, opens the pane right of the focused pane, or closes it. The action is `sysmon` in `rex/sysmon.lua`.
- It shows the mod's sections:
  - pressure, CPU with its history and per-core bars, steal and iowait
  - memory, swap, disk and load
  - load by worktree
  - process counts against an hour ago
  - listening ports, marking a dev port whose folder changed in the last hour
  - Postgres connections, Docker disk use and recent test runs
- Like the mod, it writes `~/.local/state/sysmon/groups.json` every 5 seconds. It keeps its own port memory in `rex-ports.json` beside it.
- Keys: `↑↓`/`jk` or the wheel scroll, `q` closes.

Add the action on each Rex server that should have it, then reload:

```sh
echo 'dofile(os.getenv("HOME") .. "/Development/skills/mods/sysmon/rex/sysmon.lua")' >> ~/.config/rex/init.lua
rex config reload
```
