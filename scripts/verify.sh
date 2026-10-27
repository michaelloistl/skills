#!/usr/bin/env bash
# drive-spec's verify gate: every unittest suite in the repo, one per directory holding test_*.py.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2
status=0
while IFS= read -r dir; do
  echo "== $dir"
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$dir" || status=1
done < <(git ls-files -co --exclude-standard -- '*test_*.py' | xargs -n1 dirname | sort -u)
exit $status
