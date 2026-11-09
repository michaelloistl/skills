#!/usr/bin/env bash
# Symlinks all skills into skill target directories, and hooks into each ~/.claude*/hooks, for local development.
# Run once after cloning, and again whenever you add a new skill folder or hook.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$REPO/skills"
HOOKS_DIR="$REPO/hooks"

TARGET_DIRS=("$HOME/.agents/skills")

for claude_dir in "$HOME"/.claude*/; do
  [ -d "$claude_dir" ] && TARGET_DIRS+=("${claude_dir%/}/skills")
done

link_skills_to() {
  local TARGET_DIR="$1"

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

  echo "Done. Skills available at $TARGET_DIR"
}

link_hooks_to() {
  local TARGET_DIR="$1"
  mkdir -p "$TARGET_DIR"

  for hook in "$HOOKS_DIR"/block-*; do
    [ -f "$hook" ] || continue
    hook_name="$(basename "$hook")"
    target="$TARGET_DIR/$hook_name"

    if [ -L "$target" ] && [ "$(readlink "$target")" = "$hook" ]; then
      echo "  ok  $hook_name"
      continue
    fi

    if [ -L "$target" ]; then
      rm "$target"
    elif [ -e "$target" ]; then
      echo "SKIP $hook_name — $target is a real file, remove it manually"
      continue
    fi

    ln -s "$hook" "$target"
    echo "linked $hook_name"
  done
}

for dir in "${TARGET_DIRS[@]}"; do
  echo ""
  echo "==> $dir"
  link_skills_to "$dir"
done

for claude_dir in "$HOME"/.claude*/; do
  [ -d "$claude_dir" ] || continue
  echo ""
  echo "==> ${claude_dir%/}/hooks"
  link_hooks_to "${claude_dir%/}/hooks"
done
