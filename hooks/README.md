# Hooks

Claude Code hooks. Each is symlinked into `~/.claude/hooks/` (and any other config dir) and registered in that dir's `settings.json`. No state.

- `block-unbounded-wait.sh` (PreToolUse, matcher `Bash`): denies a `while`/`until` loop with `sleep` not bounded by `timeout <n>`. Such a loop, waiting on a background task that dies first, never ends and keeps the session busy. The refusal points the agent at the task's exit notification, or at `timeout 600 sh -c 'until …; do sleep 5; done'`.

```json
{"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/hooks/block-unbounded-wait.sh"}]}
```
