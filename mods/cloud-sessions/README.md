# cloud-sessions

Your Claude Code cloud sessions at a glance: which need you, which are working, which are done. A Rex pane, `rex/cloud_sessions.py`, a terminal program using only the Python 3 standard library. macOS only: it reads the sign-in from the keychain and opens links with `open`.

- **Source:** `GET https://api.anthropic.com/v1/sessions`, the claude.ai sessions API Claude Code itself uses, with the `ccr-byoc-2025-07-29` beta. It is not public, so it can change without notice: the call is `fetch` in the script.
- **Accounts:** every Claude Code config folder with a claude.ai sign-in: `~/.claude`, and each `~/.claude-*` whose `.claude.json` names an `oauthAccount.organizationUuid`. `--config-dir` picks folders instead, and is repeatable. Sessions from all of them merge into one list. With more than one account, each card names its account, such as `claude-on`.
- **Sign-in:** each folder's OAuth token comes from the keychain:
  - Any folder: `Claude Code-credentials-` plus the first 8 hex digits of the SHA-256 of the folder's absolute path. Claude Code stores it there whenever `CLAUDE_CONFIG_DIR` is set.
  - `~/.claude` only: then `Claude Code-credentials`, the item Claude Code uses when `CLAUDE_CONFIG_DIR` is unset.
  
  On a 401 it tries the next item. When every item is refused, it says which `CLAUDE_CONFIG_DIR` to run `claude` under once to refresh the token. The organisation comes from that folder's `.claude.json`. A failed account shows its error at the top and keeps its last cards.
- **State:** each session's state comes from `session_status` while it runs, starts, fails or waits on an approval. For an `idle` session it comes from `status_bucket`, the server's own sorting, else from the last turn's `post_turn_summary.status_category`. A finished turn whose `needs_action` names something counts as needing input. The groups, in order:
  - **Needs you:**
    - `⚠ needs approval` (`requires_action`)
    - `✗ failed`
    - `? needs input` (`need_input` or `blocked`)
    - `◆ ready for review` (`review_ready`)
  - **Working:**
    - `↻ running`
    - `◌ starting` (`pending`)
    - `◷ working · idle`: the bucket is `working` between turns, such as a build loop waiting
  - **Done:** `✓ done` (`completed`). This group is left out when it is empty.
- **Hidden:** `archived` sessions, and done or failed ones not updated for 2 days (`--max-age`).
- **Cards:** each session is a card, bordered in its state's colour. Lines that have nothing to show are left out.
  - **Top border:** the key, glyph, title, state, time since the last update, and `●` while unread.
  - **Headline:** for an approval, the tool from `external_metadata.pending_action`, its `display_tool_name` else `tool_name`. For a failure, the reason. Otherwise the turn's `status_detail`. Up to 2 lines.
  - **`→`** the turn's `needs_action`, in yellow.
  - **`↻`** the live `task_summary` while running.
  - **Recent action:** the turn's `recent_action`, dim, up to 2 lines.
  - **Repo:** the repo's name and branch, from `session_context.outcomes` and `external_metadata.current_branches`, with `⚑ unpushed` for `unpushed_work`.
  - **Facts:** context used (`context_usage`), cost (`usage.cost_usd`), model, account (only with more than one account), and `offline` when `connection_status` is `disconnected`.
- **Width:** cards fill the pane, up to 100 columns.
- **Refresh:** every 30 seconds (`--interval`). A failed fetch shows the error and keeps the last list.
- **Notification:** a macOS notification when a session starts needing you, or moves to another needs-you state. Not on the first fetch. `--no-notify` turns it off.
- **Open:** a session's card behaves like a link. Under the pointer, its title is underlined, its recent action shows up to 6 lines, and a pending approval shows what it is for, up to 6 lines: the action's `action_description`, then its `input`'s `command`, `file_path`, `url` or similar field, else the input as JSON. The pointer becomes a hand where the terminal supports OSC 22. A click anywhere on the card, or the key in its top border, opens it on claude.ai/code. The pane turns on the terminal's SGR mouse reporting, clicks and motion, while it runs.
- **Keys:** `r` refreshes, `q` quits.
- `--once` prints the list and exits, without colours when not printing to a terminal. `--json` prints the parsed sessions instead, and `--raw` what the API returned for each account.

## Rex pane

`alt+cmd+c`, or Toggle Cloud Sessions in the command palette, opens the list to the right of the focused pane, or closes it. The action is `cloud_sessions` in `rex/cloud_sessions.lua`. Add it to the Rex server's `init.lua` and reload:

```sh
echo 'dofile(os.getenv("HOME") .. "/Development/skills/mods/cloud-sessions/rex/cloud_sessions.lua")' >> ~/.config/rex/init.lua
rex config reload
```

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s mods/cloud-sessions/rex
```
