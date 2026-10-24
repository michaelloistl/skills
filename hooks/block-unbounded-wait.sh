#!/usr/bin/env bash
# PreToolUse/Bash guard: block a `while`/`until` loop that sleeps without a
# `timeout` bound. Such a loop waiting on a background task's output never ends
# when the task dies first, and keeps the session busy forever.
set -uo pipefail

cmd=$(jq -r '.tool_input.command // ""')

printf '%s' "$cmd" | grep -qE '(^|[^[:alnum:]_-])(while|until)[[:space:]]' || exit 0
printf '%s' "$cmd" | grep -qE '(^|[^[:alnum:]_-])sleep[[:space:]]' || exit 0
printf '%s' "$cmd" | grep -qE '(^|[^[:alnum:]_-])timeout[[:space:]]+(-[^[:space:]]+[[:space:]]+)*[0-9]' && exit 0

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"This polls in a while/until loop with sleep and no time bound: if what it waits for never appears (the task died, the word never prints), it runs forever and the session stays busy. A background task already notifies you when it exits: end your turn or keep working, and act on the notification. When you must poll, bound it: timeout 600 sh -c 'until …; do sleep 5; done'."}}
JSON
exit 0
