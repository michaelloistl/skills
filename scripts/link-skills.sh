#!/usr/bin/env bash
# Symlinks all skills into ~/.agents/skills/ for local development.
# Run once after cloning, and again whenever you add a new skill folder.
# Skills become immediately available to both ~/.claude and ~/.claude-on.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$REPO/skills"
TARGET_DIR="$HOME/.agents/skills"

# Bail if TARGET_DIR is a symlink that resolves back into this repo.
if [ -L "$TARGET_DIR" ]; then
  resolved="$(readlink -f "$TARGET_DIR")"
  case "$resolved" in
    "$REPO"|"$REPO"/*)
      echo "error: $TARGET_DIR is a symlink into this repo ($resolved)." >&2
      echo "Remove it (rm \"$TARGET_DIR\") and re-run; the script will recreate it as a real dir." >&2
      exit 1
      ;;
  esac
fi

mkdir -p "$TARGET_DIR"

find "$SKILLS_DIR" -name "SKILL.md" \
  -not -path '*/node_modules/*' \
  -not -path '*/deprecated/*' \
  -print0 |
while IFS= read -r -d '' skill_md; do
  skill_dir="$(dirname "$skill_md")"
  skill_name="$(basename "$skill_dir")"
  target="$TARGET_DIR/$skill_name"

  # Skip if target already points to this skill
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$skill_dir" ]; then
    echo "  ok  $skill_name"
    continue
  fi

  # Remove stale symlink or warn about real directory
  if [ -L "$target" ]; then
    rm "$target"
  elif [ -d "$target" ]; then
    echo "SKIP $skill_name — $target is a real directory, remove it manually"
    continue
  fi

  ln -s "$skill_dir" "$target"
  echo "linked $skill_name"
done

echo ""
echo "Done. Skills available at $TARGET_DIR"
