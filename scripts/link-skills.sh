#!/usr/bin/env bash
# Symlinks all skills into ~/.agents/skills/ for local development.
# Run once after cloning, and again whenever you add a new skill folder.
# Skills become immediately available to both ~/.claude and ~/.claude-on.

set -euo pipefail

SKILLS_DIR="$(cd "$(dirname "$0")/../skills" && pwd)"
TARGET_DIR="$HOME/.agents/skills"

mkdir -p "$TARGET_DIR"

find "$SKILLS_DIR" -mindepth 3 -maxdepth 3 -name "SKILL.md" | while read -r skill_md; do
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
