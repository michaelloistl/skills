#!/usr/bin/env bash
set -uo pipefail

cmd=$(jq -r '.tool_input.command // ""')

printf '%s' "$cmd" | grep -qE '(^|[;&|(`[:space:]])git([[:space:]]+(-[Cc][[:space:]]+[^[:space:]]+|--?[[:alnum:]-]+(=[^[:space:]]*)?))*[[:space:]]+stash([[:space:]]|$)' || exit 0
all=$(printf '%s' "$cmd" | grep -oE 'stash([[:space:]]+[[:alnum:]-]+)?' | grep -cvE 'stash[[:space:]]+(list|show)$')
[ "$all" -eq 0 ] && exit 0

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"git stash keeps one stack per repository, shared by every worktree and every session in this checkout: a pop can hand you another session's changes, or hand yours to it. To set changes aside, save a patch and restore it: git diff -- <paths> > /tmp/<name>.patch && git checkout -- <paths>, later git apply /tmp/<name>.patch. To see the code before your change, read it with git show HEAD:<path>, or commit the test first and run it there. git stash list and git stash show stay allowed."}}
JSON
exit 0
