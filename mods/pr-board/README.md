# pr-board

A Claude Code mod: a pane listing the session repo's open PRs.

- `/prs` toggles the pane; `/prs pin <n>` and `/prs unpin` set this session's PR. It refreshes on open, on Refresh, and every 2 minutes while open.
- Each PR row: checks (`✓` pass, `✗` fail, `●` pending), review state or `conflicts`, title, author. Under it, the GitHub issues the PR closes or names as `#123` in its body, each with the Linear issue that Linear's linkback comment names.
- Each PR is a card bordered by its health: red for failing CI or conflicts, yellow for pending or changes requested, green approved, grey draft.
- This session's PR comes first, in a bold orange border marked `◉ this session` and why: `pinned` (`⋯` → Pin to this session, or `/prs pin <n>`; `/prs unpin` clears it), else `most referenced` (the open PR the person's prompts and the session's tool calls name most in the last 400 messages, read after each turn), else `branch` (the PR whose head is checked out in the session's folder, read every 5 seconds while the pane is open). A branch with no PR shows as its own `no PR` card.
- PR, issue, spec and Linear numbers are buttons that open the page in the browser.
- `⋯` shows the PR's actions. Each starts a Rex session `<action>-<pr>` running `claude --worktree` under the same `CLAUDE_CONFIG_DIR`, with the action's prompt: Fix CI, Resolve conflicts (`/resolving-merge-conflicts`). Prompts live in `ACTIONS` in `hooks/register.tsx`.
- drive-spec runs, each with a progress bar from its `landed n/m`: on each host in the `driveSpecHosts` option (default `local,devbox`; `local` is this machine, anything else an ssh host), the mod runs `dispatch status --json` in the same repo path under `$HOME`, with the dispatch skill from `~/.claude-on` or `~/.claude`. A run shows under its spec PR, or under `drive-spec · no PR yet` when it has none open; a finished run whose PR closed is left out, as is one dispatch acked or one with no status file. A slice PR, based on `agent/local-spec-<n>-…`, reads `slice of spec #<n>`.

Loaded from this folder via `CLAUDE_CODE_PLUGIN_DIRS` in the `env` of `~/.claude/settings.json` and `~/.claude-on/settings.json`. Set the option under `pluginConfigs` in settings, or in `/config`.

```sh
claude plugin validate mods/pr-board
claude plugin test mods/pr-board
```
