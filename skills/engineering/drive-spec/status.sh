#!/usr/bin/env bash
# Usage: status.sh <spec> [key=value ...] | status.sh <spec> --inbox
set -u

spec=${1:-}
[ -n "$spec" ] || exit 0
shift

write() {
  command -v jq >/dev/null || return 1
  local common dir file tmp now args
  common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  dir="$common/drive-spec/status"
  file="$dir/spec-$spec.json"
  mkdir -p "$dir" || return 1
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  args=(--arg spec "$spec" --arg now "$now"
    --arg session "${CLAUDE_CODE_SESSION_ID:-}" --arg pane "${HERDR_PANE_ID:-}"
    --arg host "$(hostname)" --arg repo "$(git remote get-url origin 2>/dev/null)")
  local updates='{}' pair key value
  for pair in "$@"; do
    key=${pair%%=*}
    value=${pair#*=}
    case "$key" in
      step|state|summary|next|pr_url|branch|base|question) ;;
      question_blocking) value=$([ "$value" = true ] && echo true || echo false) ;;
      *) echo "status.sh: unknown key $key" >&2; continue ;;
    esac
    updates=$(jq -c --arg k "$key" --arg v "$value" \
      'if $k == "question_blocking" then .[$k] = ($v == "true")
       elif $v == "" then .[$k] = null else .[$k] = $v end' <<<"$updates") || return 1
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
      | .herdr_pane = (if $pane == "" then .herdr_pane else $pane end)
      | if .question == null then .question_blocking = false else . end
    ' >"$tmp" && mv -f "$tmp" "$file" || { rm -f "$tmp"; return 1; }
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
else
  write "$@" || echo "status.sh: status for spec $spec not written" >&2
fi
exit 0
