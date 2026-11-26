# cloud-sessions

Your Claude Code cloud sessions at a glance: which need you, which are working. A Rex pane, `rex/cloud_sessions.py`, a terminal program using only the Python 3 standard library. macOS only: it reads the sign-in from the keychain and opens links with `open`.

- **Source:** `GET https://api.anthropic.com/v1/sessions`, the claude.ai sessions API Claude Code itself uses, with the `ccr-byoc-2025-07-29` beta. It is not public, so it can change without notice: the call is `fetch` in the script.
- **Accounts:** every Claude Code config folder with a claude.ai sign-in: `~/.claude`, and each `~/.claude-*` whose `.claude.json` names an `oauthAccount.organizationUuid`. `--config-dir` picks folders instead, and is repeatable. Sessions from all of them merge into one list. With more than one account, each row names its account, such as `claude-on`.
- **Sign-in:** each folder's OAuth token comes from the keychain:
  - Any folder: `Claude Code-credentials-` plus the first 8 hex digits of the SHA-256 of the folder's absolute path. Claude Code stores it there whenever `CLAUDE_CONFIG_DIR` is set.
  - `~/.claude` only: then `Claude Code-credentials`, the item Claude Code uses when `CLAUDE_CONFIG_DIR` is unset.
  
  On a 401 it tries the next item. When every item is refused, it says which `CLAUDE_CONFIG_DIR` to run `claude` under once to refresh the token. The organisation comes from that folder's `.claude.json`. A failed account shows its error at the top and keeps its last rows.
- **Needs you:** by `session_status`, in this order:
  - `⚠ needs approval`, for `requires_action`. Below it, the tool from `external_metadata.pending_action`.
  - `✗ failed`. Below it, the reason.
  - `● awaiting reply`, for `idle`: the turn finished.
- **Working:** `↻ running` and `◌ starting` (`pending`).
- **Hidden:** `archived` sessions, and `idle` or `failed` ones not updated for 2 days (`--max-age`). A session waiting for approval always shows.
- Each row shows the session's title, its state, `· offline` when its connection is `disconnected`, and the time since it was last updated.
- **Refresh:** every 30 seconds (`--interval`). A failed fetch shows the error and keeps the last list.
- **Notification:** a macOS notification when a session starts needing you, or moves to another needs-you state. Not on the first fetch. `--no-notify` turns it off.
- **Open:** a click on a session's row or the line under it, or the key before the row, opens that session on claude.ai/code. The pane turns on the terminal's SGR mouse reporting while it runs.
- **Keys:** `r` refreshes, `q` quits.
- `--once` prints the list and exits, without colours when not printing to a terminal. `--json` prints the rows instead.

## Rex pane

`alt+cmd+c`, or Toggle Cloud Sessions in the command palette, opens the list to the right of the focused pane, or closes it. The action is `cloud_sessions` in `rex/cloud_sessions.lua`. Add it to the Rex server's `init.lua` and reload:

```sh
echo 'dofile(os.getenv("HOME") .. "/Development/skills/mods/cloud-sessions/rex/cloud_sessions.lua")' >> ~/.config/rex/init.lua
rex config reload
```

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s mods/cloud-sessions/rex
```
