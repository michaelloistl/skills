#!/usr/bin/env bash
# Push the Mac's Claude configs (~/.claude personal, ~/.claude-on ON subscription) to a dev box.
# Run from the Mac after setup.sh has finished on the box. Idempotent: re-run to sync config changes.
#   scripts/devbox-push-claude-config.sh workbox
# Credentials are not copied: log in once per config on the box (`claude` in a personal dir and in on-vantage).
set -euo pipefail

HOST="${1:?usage: $0 <ssh-host>}"
RSYNC=(rsync -a --exclude .DS_Store)

echo "==> ~/.claude"
ssh "$HOST" 'mkdir -p ~/.claude/hooks ~/.claude-on/hooks ~/.agents/skills'
"${RSYNC[@]}" ~/.claude/CLAUDE.md ~/.claude/settings.json ~/.claude/statusline-command.sh ~/.claude/commands "$HOST":.claude/
"${RSYNC[@]}" ~/.claude/hooks/block-claude-attribution.sh "$HOST":.claude/hooks/

echo "==> ~/.claude-on"
"${RSYNC[@]}" ~/.claude-on/CLAUDE.md ~/.claude-on/settings.json "$HOST":.claude-on/
"${RSYNC[@]}" ~/.claude-on/hooks/block-claude-attribution.sh "$HOST":.claude-on/hooks/

# dev-up has no upstream repo; copy the real dir
echo "==> dev-up skill"
"${RSYNC[@]}" ~/.agents/skills/dev-up "$HOST":.agents/skills/

echo "==> remote fixups"
ssh "$HOST" MAC_HOME="$HOME" bash -s <<'REMOTE'
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

# .claude-on shares skills, commands and statusline with .claude (same as the Mac)
ln -sfn ~/.agents/skills ~/.claude-on/skills
ln -sfn ~/.claude/commands ~/.claude-on/commands
ln -sfn ~/.claude/statusline-command.sh ~/.claude-on/statusline-command.sh
[ -e ~/.claude/skills/dev-up ] || ln -s ../../.agents/skills/dev-up ~/.claude/skills/dev-up

for d in ~/.claude ~/.claude-on; do
  sed -i "s#$MAC_HOME#$HOME#g" "$d/settings.json"
done

if command -v herdr >/dev/null; then
  herdr integration install claude >/dev/null
  cp ~/.claude/hooks/herdr-agent-state.sh ~/.claude-on/hooks/
else
  # no herdr on the box (yet): drop its hook so sessions don't error; re-run after `herdr machine add`
  for d in ~/.claude ~/.claude-on; do
    tmp=$(mktemp)
    jq '(.hooks // {}) |= with_entries(.value |= (map(.hooks |= map(select(.command | test("herdr-agent-state") | not))) | map(select(.hooks | length > 0))))' \
      "$d/settings.json" > "$tmp" && mv "$tmp" "$d/settings.json"
  done
fi

for d in ~/.claude ~/.claude-on; do
  jq empty "$d/settings.json"
  missing=$(jq -r '.. | .command? // empty' "$d/settings.json" | grep -oE "(~|$HOME)/[^\"' ]+\.sh" | sed "s#^~#$HOME#" | while read -r f; do [ -f "$f" ] || echo "$f"; done)
  [ -z "$missing" ] || { echo "WARN $d/settings.json references missing: $missing"; }
done
echo "skills: $(ls ~/.claude/skills | wc -l) in .claude, $(ls ~/.claude-on/skills/ | wc -l) in .claude-on"
REMOTE

echo "Done. Log in once per config on $HOST: \`claude\` in ~ (personal) and in ~/Development/on/on-vantage (ON)."
