# Hooks

Claude Code hooks. Each is symlinked into `~/.claude/hooks/` (and any other config dir) and registered in that dir's `settings.json`. No state. Tests: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s hooks`.

- `block-claude-attribution.sh` (PreToolUse, matcher `Bash`): denies `gh pr|issue create|edit` whose body carries a Claude Code attribution footer.
- `block-unbounded-wait.sh` (PreToolUse, matcher `Bash`): denies a `while`/`until` loop with `sleep` not bounded by `timeout <n>`. Such a loop, waiting on a background task that dies first, never ends and keeps the session busy. The refusal points the agent at the task's exit notification, or at `timeout 600 sh -c 'until …; do sleep 5; done'`.
- `block-git-stash.sh` (PreToolUse, matcher `Bash`): denies `git stash` other than `list` and `show`. The stash stack is one per repository, shared by every worktree and session in the checkout, so a pop can swap changes between sessions. The refusal points the agent at a patch file (`git diff … > /tmp/x.patch`, `git apply`) or `git show HEAD:<path>`.
- `block-drive-spec-pipe.py` (PreToolUse, matcher `Bash`): denies piping a `drive-spec` command's output (`drive-spec open … | tail`, or `$D open … | tail` with `D=…/drive-spec`). Its exit code is the verdict (2 refused, 3 conflict, 4 red, 5 inbox notes), and a pipe reports the last stage's exit instead. Piping into it, as `--deviations -` and `--left -` read stdin, stays allowed.

```json
{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "~/.claude/hooks/block-claude-attribution.sh"},
  {"type": "command", "command": "~/.claude/hooks/block-unbounded-wait.sh"},
  {"type": "command", "command": "~/.claude/hooks/block-git-stash.sh"},
  {"type": "command", "command": "~/.claude/hooks/block-drive-spec-pipe.py"}
]}
```
