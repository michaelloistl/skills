#!/usr/bin/env bash
# Usage: status.sh <spec> [key=value ...] (agents=<JSON object>) | status.sh <spec> --inbox | status.sh <spec> --touch
set -u

spec=${1:-}
[ -n "$spec" ] || exit 0
shift

# A write and the --touch heartbeat each read, rewrite and rename the file: run them one at a time per spec,
# so one never puts back what another just wrote. Re-runs this script holding an flock on .spec-<spec>.lock.
if [ "${1:-}" != --inbox ] && [ -z "${DRIVE_SPEC_STATUS_LOCKED:-}" ] && command -v python3 >/dev/null; then
  common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) &&
    mkdir -p "$common/drive-spec/status" &&
    DRIVE_SPEC_STATUS_LOCKED=1 exec python3 -c '
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX)
os.set_inheritable(fd, True)
os.execv(sys.argv[2], sys.argv[2:])
' "$common/drive-spec/status/.spec-$spec.lock" "$BASH" "$0" "$spec" "$@"
fi

write() {
  command -v jq >/dev/null || return 1
  local common dir file tmp now args
  common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  dir="$common/drive-spec/status"
  file="$dir/spec-$spec.json"
  mkdir -p "$dir" || return 1
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  local pane=${HERDR_PANE_ID:-} mux=herdr
  [ -n "$pane" ] || { pane=${REX_BLOCK:-}; mux=rex; }
  args=(--arg spec "$spec" --arg now "$now"
    --arg session "${CLAUDE_CODE_SESSION_ID:-}" --arg pane "$pane" --arg mux "$mux"
    --arg config "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
    --arg host "$(hostname)" --arg repo "$(git remote get-url origin 2>/dev/null)")
  local updates='{}' pair key value
  for pair in "$@"; do
    key=${pair%%=*}
    value=${pair#*=}
    case "$key" in
      step|state|summary|next|pr_url|branch|base|question) ;;
      question_blocking|sequential) value=$([ "$value" = true ] && echo true || echo false) ;;
      max) [ -z "$value" ] || [[ "$value" =~ ^[0-9]+$ ]] ||
        { echo "status.sh: max is not a number" >&2; continue; } ;;
      agents)
        updates=$(jq -c --argjson v "$value" '.agents = $v' <<<"$updates") ||
          { echo "status.sh: agents is not JSON" >&2; return 1; }
        continue ;;
      *) echo "status.sh: unknown key $key" >&2; continue ;;
    esac
    updates=$(jq -c --arg k "$key" --arg v "$value" \
      'if $k == "question_blocking" or $k == "sequential" then .[$k] = ($v == "true")
       elif $v == "" then .[$k] = null elif $k == "max" then .[$k] = ($v | tonumber) else .[$k] = $v end' <<<"$updates") || return 1
  done

  tmp=$(mktemp "$dir/.spec-$spec.XXXXXX") || return 1
  { [ -s "$file" ] && cat "$file" || echo '{}'; } |
    jq "${args[@]}" --argjson u "$updates" '
      . + $u
      | .spec = ($spec | tonumber? // $spec)
      | .updated_at = $now
      | .host = $host
      | .repo = (if $repo == "" then .repo else $repo end)
      | .session_id = (if $session == "" then .session_id else $session end)
      | .config_dir = (if $session == "" then .config_dir else $config end)
      | if $pane == "" then . else .pane = $pane | .mux = $mux | del(.herdr_pane) end
      | if .question == null then .question_blocking = false else . end
    ' >"$tmp" && mv -f "$tmp" "$file" || { rm -f "$tmp"; return 1; }
}

touch_() {
  command -v jq >/dev/null || return 1
  local common file tmp
  common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  file="$common/drive-spec/status/spec-$spec.json"
  [ -s "$file" ] || return 0
  tmp=$(mktemp "${file%/*}/.spec-$spec.XXXXXX") || return 1
  jq --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '.updated_at = $now' "$file" >"$tmp" && mv -f "$tmp" "$file" ||
    { rm -f "$tmp"; return 1; }
}

inbox() {
  local common dir reading
  common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  dir="$common/drive-spec/status"
  [ -s "$dir/spec-$spec.inbox.md" ] || return 0
  reading=$(mktemp "$dir/.spec-$spec.inbox.XXXXXX") || return 1
  mv -f "$dir/spec-$spec.inbox.md" "$reading" || return 1
  cat "$reading"
  cat "$reading" >>"$dir/spec-$spec.inbox-read.md"
  rm -f "$reading"
}

if [ "${1:-}" = --inbox ]; then
  inbox || echo "status.sh: inbox for spec $spec not read" >&2
elif [ "${1:-}" = --touch ]; then
  touch_ || echo "status.sh: status for spec $spec not touched" >&2
else
  write "$@" || echo "status.sh: status for spec $spec not written" >&2
fi
exit 0
