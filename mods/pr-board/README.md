# pr-board

A Claude Code mod: a pane listing the session repo's open PRs.

- `/prs` toggles the pane. It refreshes on open, on Refresh, and every 2 minutes while open.
- Each PR row: checks (`✓` pass, `✗` fail, `●` pending), review state or `conflicts`, title, author. Under it, the GitHub issues the PR closes or names as `#123` in its body, each with the Linear issue that Linear's linkback comment names.
- PR, issue, spec and Linear numbers are buttons that open the page in the browser.
- `⋯` shows the PR's actions. Each starts a Rex session `<action>-<pr>` running `claude --worktree` under the same `CLAUDE_CONFIG_DIR`, with the action's prompt: Fix CI, Resolve conflicts (`/resolving-merge-conflicts`). Prompts live in `ACTIONS` in `hooks/register.tsx`.
- drive-spec runs: on each host in the `driveSpecHosts` option (default `local,devbox`; `local` is this machine, anything else an ssh host), the mod runs `dispatch status --json` in the same repo path under `$HOME`, with the dispatch skill from `~/.claude-on` or `~/.claude`. A run shows under its spec PR, or under `drive-spec runs` when it has no open PR yet; a finished run whose PR closed is left out, as is one dispatch acked. A slice PR, based on `agent/local-spec-<n>-…`, reads `slice of spec #<n>`.

Loaded from this folder via `CLAUDE_CODE_PLUGIN_DIRS` in the `env` of `~/.claude/settings.json` and `~/.claude-on/settings.json`. Set the option under `pluginConfigs` in settings, or in `/config`.

```sh
claude plugin validate mods/pr-board
claude plugin test mods/pr-board
```
