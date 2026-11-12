# sysmon

The System pane of the sysmon Claude Code mod as a Rex pane. The mod itself lives on the devbox in `~/.claude-on/mods/sysmon`.

`rex/sysmon.py` is a terminal program using only the Python 3 standard library. It reads `/proc`, so it runs in Linux sessions, such as devbox ones. In a Mac session it says so and closes on any key.

- `shift+cmd+m`, or Toggle System Monitor in the command palette, opens the pane right of the focused pane, or closes it. The action is `sysmon` in `rex/sysmon.lua`.
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
