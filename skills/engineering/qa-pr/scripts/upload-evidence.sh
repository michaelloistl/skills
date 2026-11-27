#!/usr/bin/env bash
# Commit files to the evidence branch with git and push it: a cloud session's
# GitHub proxy refuses REST writes to git data and contents (403), but lets
# git push a new branch. Run inside the repo's checkout; the work tree, index
# and HEAD stay untouched.
set -euo pipefail

repo="${1:?usage: upload-evidence.sh <owner/repo> <branch> <dir in branch> <file>...}"
branch="${2:?}"
dest="${3:?}"
shift 3

tip=refs/qa-pr/evidence-tip
index=$(mktemp -u)
trap 'rm -f "$index"' EXIT

# Retry: another QA run may push the branch between our fetch and push.
for attempt in 1 2 3; do
  rm -f "$index"
  if git fetch -q origin "+refs/heads/$branch:$tip" 2>/dev/null; then
    parent=$(git rev-parse "$tip")
    GIT_INDEX_FILE=$index git read-tree "$parent"
  else
    parent=
    readme=$(printf '# QA evidence\n\nScreenshots that qa-pr comments embed. Nothing merges from here.\n' | git hash-object -w --stdin)
    GIT_INDEX_FILE=$index git update-index --add --cacheinfo "100644,$readme,README.md"
  fi
  for file in "$@"; do
    blob=$(git hash-object -w "$file")
    GIT_INDEX_FILE=$index git update-index --add --cacheinfo "100644,$blob,$dest/$(basename "$file")"
  done
  tree=$(GIT_INDEX_FILE=$index git write-tree)
  commit=$(git commit-tree "$tree" ${parent:+-p "$parent"} -m "Add QA evidence $dest")
  if git push -q origin "$commit:refs/heads/$branch"; then break; fi
  if [ "$attempt" = 3 ]; then echo "upload-evidence: push to $branch failed" >&2; exit 1; fi
done

for file in "$@"; do
  printf '%s\thttps://github.com/%s/blob/%s/%s/%s?raw=true\n' "$file" "$repo" "$branch" "$dest" "$(basename "$file")"
done
