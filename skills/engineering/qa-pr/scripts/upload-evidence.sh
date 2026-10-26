#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: upload-evidence.sh <owner/repo> <branch> <dir in branch> <file>...}"
branch="${2:?}"
dest="${3:?}"
shift 3

if ! gh api "repos/$repo/branches/$branch" --silent 2>/dev/null; then
  blob=$(printf '# QA evidence\n\nScreenshots that qa-pr comments embed. Nothing merges from here.\n' |
    jq -Rs '{content: ., encoding: "utf-8"}' | gh api "repos/$repo/git/blobs" --input - --jq .sha)
  tree=$(gh api "repos/$repo/git/trees" -f "tree[][path]=README.md" -f "tree[][mode]=100644" -f "tree[][type]=blob" -f "tree[][sha]=$blob" --jq .sha)
  commit=$(gh api "repos/$repo/git/commits" -f message="Start QA evidence" -f tree="$tree" --jq .sha)
  gh api "repos/$repo/git/refs" -f ref="refs/heads/$branch" -f sha="$commit" --silent
fi

for file in "$@"; do
  path="$dest/$(basename "$file")"
  sha=$(gh api "repos/$repo/contents/$path?ref=$branch" --jq .sha 2>/dev/null || true)
  base64 < "$file" | tr -d '\n' |
    jq -Rs --arg message "Add $path" --arg branch "$branch" --arg sha "$sha" \
      '{message: $message, branch: $branch, content: .} + (if $sha == "" then {} else {sha: $sha} end)' |
    gh api -X PUT "repos/$repo/contents/$path" --input - --silent
  printf '%s\thttps://github.com/%s/blob/%s/%s?raw=true\n' "$file" "$repo" "$branch" "$path"
done
