# pr-board

A Claude Code mod: a pane listing the session repo's open PRs.

- `/prs` toggles the pane, at once even mid-turn; `/prs pin <n>` and `/prs unpin` set this session's PR. It refreshes on open, on Refresh, and every 2 minutes while open.
- Each PR row: checks (`✓` pass, `✗` fail, `●` pending), review state or `conflicts`, title, author. Under it, the GitHub issues the PR closes or names as `#123` in its body, each with the Linear issue that Linear's linkback comment names.
- Each PR is a card bordered by its health: red for failing CI or conflicts, yellow for pending or changes requested, green approved, grey draft.
- This session's PR comes first, in a bold orange border marked `◉ this session` and why: `pinned` (`⋯` → Pin to this session, or `/prs pin <n>`; `/prs unpin` clears it), else `most referenced` (the open PR the person's prompts and the session's tool calls name most in the last 400 messages, read after each turn), else `branch` (the PR whose head is checked out in the session's folder, read every 5 seconds while the pane is open). A branch with no PR shows as its own `no PR` card.
- PR, issue, spec and Linear numbers are buttons that open the page in the browser on macOS; elsewhere, such as a devbox, they copy the URL to the clipboard.
- `⋯` shows the PR's actions. Each starts a Rex session `<action>-<pr>` running `claude --worktree` under the same `CLAUDE_CONFIG_DIR`, with the action's prompt: Fix CI, Resolve conflicts (`/resolving-merge-conflicts`). Prompts live in `ACTIONS` in `hooks/register.tsx`.
- drive-spec runs, each with a progress bar from its `landed n/m`: on each host in the `driveSpecHosts` option (default `local,devbox`; `local` is this machine, anything else an ssh host), the mod runs `dispatch status --json` in the same repo path under `$HOME`, with the dispatch skill from `~/.claude-on` or `~/.claude`. A run shows under its spec PR, or under `drive-spec · no PR yet` when it has none open; a finished run whose PR closed is left out, as is one dispatch acked or one with no status file. A slice PR, based on `agent/local-spec-<n>-…`, reads `slice of spec #<n>`. Under each spec, `⤷ merged` lists up to four of its slice PRs merged in the last day, newest first, with their age.

Loaded from this folder via `CLAUDE_CODE_PLUGIN_DIRS` in the `env` of `~/.claude/settings.json` and `~/.claude-on/settings.json`. Set the option under `pluginConfigs` in settings, or in `/config`.

```sh
claude plugin validate mods/pr-board
claude plugin test mods/pr-board
```

## Rex pane

The same board as a terminal program in a Rex split, independent of any Claude session: `rex/pr_board.py`, Python 3 standard library only.

- `shift+cmd+o`, or Toggle Open PRs in the command palette, opens the board right of the focused pane, or closes it. The action is `pr_board` in `rex/pr_board.lua`.
- The board follows the pane it opened beside, reading it every 5 seconds through the Rex API. It reads the folder, repo and branch of the program in the foreground. When that program is Claude, it also reads the session from `~/.claude*/sessions/<pid>.json` and finds the PR the session references most in its transcript. The session PR rules match the mod's.
- Keys: `↑↓`/`jk` select a PR, `⏎`/`o` open it, `␣`/`a` show its actions, `f` Fix CI, `c` Resolve conflicts, `p` pin it to the followed session, `r` refresh, `q` close. A click works on any number, `⋯`, an action or `↻ refresh`, and the wheel scrolls.
- On macOS, links open in the browser. Elsewhere, such as a devbox, they copy to the clipboard through OSC 52.
- drive-spec hosts come from the mod's `driveSpecHosts` in the followed session's settings, or `--hosts`.

The Rex server reads `init.lua` on its own machine, so add the action on each one, the Mac and the devbox:

```sh
mkdir -p ~/.config/rex
echo 'dofile(os.getenv("HOME") .. "/Development/skills/mods/pr-board/rex/pr_board.lua")' >> ~/.config/rex/init.lua
rex config reload
```
