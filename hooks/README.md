# Hooks

Claude Code hooks. Each is symlinked into `~/.claude/hooks/` (and any other config dir) and registered in that dir's `settings.json`. No state.

- `block-claude-attribution.sh` (PreToolUse, matcher `Bash`): denies `gh pr|issue create|edit` whose body carries a Claude Code attribution footer.
- `block-unbounded-wait.sh` (PreToolUse, matcher `Bash`): denies a `while`/`until` loop with `sleep` not bounded by `timeout <n>`. Such a loop, waiting on a background task that dies first, never ends and keeps the session busy. The refusal points the agent at the task's exit notification, or at `timeout 600 sh -c 'until …; do sleep 5; done'`.
- `block-git-stash.sh` (PreToolUse, matcher `Bash`): denies `git stash` other than `list` and `show`. The stash stack is one per repository, shared by every worktree and session in the checkout, so a pop can swap changes between sessions. The refusal points the agent at a patch file (`git diff … > /tmp/x.patch`, `git apply`) or `git show HEAD:<path>`.

```json
{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "~/.claude/hooks/block-claude-attribution.sh"},
  {"type": "command", "command": "~/.claude/hooks/block-unbounded-wait.sh"},
  {"type": "command", "command": "~/.claude/hooks/block-git-stash.sh"}
]}
```
