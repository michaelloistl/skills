#!/usr/bin/env bash
# PreToolUse/Bash guard: block `gh pr|issue create|edit` whose body carries a
# Claude Code attribution footer ("Generated with Claude Code" / the
# claude.com/claude-code link). Wired up in ~/.claude/settings.json.
set -uo pipefail

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""')

# Only inspect gh pr/issue create|edit commands; let everything else through.
printf '%s' "$cmd" | grep -qiE 'gh +(pr|issue) +(create|edit)' || exit 0

# Footer signatures: the canonical URL, or "generated with" + "claude code".
if printf '%s' "$cmd" | grep -qiF 'claude.com/claude-code' \
  || { printf '%s' "$cmd" | grep -qiF 'generated with' \
       && printf '%s' "$cmd" | grep -qiF 'claude code'; }; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"This gh pr/issue body contains a Claude Code attribution footer (a Generated with Claude Code line or claude.com/claude-code link). Per the user's standing rule this must never appear: remove that footer from the body and retry the command without it."}}
JSON
fi
exit 0
