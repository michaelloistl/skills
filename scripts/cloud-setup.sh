#!/usr/bin/env bash
# Setup script for Claude Code cloud environments (claude.ai/code).
# Paste into the environment's "Setup script" field. Runs as root on Ubuntu
# before Claude Code launches; the result is cached for ~7 days.
# Needs the Trusted network level (github.com, registry.npmjs.org).

set -euo pipefail

MATT_SKILLS=(
  code-review codebase-design diagnosing-bugs domain-modeling grill-with-docs
  grilling handoff implement implement-spec improve-codebase-architecture pr
  prototype research resolving-merge-conflicts retro tdd to-spec to-tickets
  triage wayfinder writing-for-agents
)

npx -y skills@latest add mattpocock/skills -g -y --agent claude-code --copy \
  --skill "${MATT_SKILLS[@]}" </dev/null
npx -y skills@latest add michaelloistl/skills -g -y --agent claude-code --copy \
  --skill '*' </dev/null

mkdir -p ~/.claude

cat > ~/.claude/CLAUDE.md <<'EOF'
Be extremely concise. Sacrifice grammar for the sake of concision.

Search code with `rg` or `git grep`: both skip ignored build output.

## Debugging

When stuck on a bug — after 3+ failed fix attempts, when about to make a low-confidence guess, or when the same assumption has been made multiple times — you MUST invoke the `debug-logs` skill instead of continuing to guess. Do not attempt another fix. Instrument the code first.

## Git

Only create commits when explicitly asked. Do not auto-commit during feature work.
Stage the paths you changed by name (`git add <path>…`).
When committing, write only the commit message subject line — leave the detailed description body empty.
Do not add Co-Authored-By lines to commit messages.
Never add a Claude Code attribution footer to any commit message, PR body, or GitHub issue body.

## GitHub in cloud sessions

The GitHub proxy rejects GraphQL, so `gh issue …` and `gh pr …` fail with 403. Use the REST API via `gh api repos/{owner}/{repo}/…` instead, e.g.:
- view issue: `gh api repos/{owner}/{repo}/issues/<n>`
- create issue: `gh api repos/{owner}/{repo}/issues -f title=… -f body=…`
- comment: `gh api repos/{owner}/{repo}/issues/<n>/comments -f body=…`
- labels: `gh api repos/{owner}/{repo}/issues/<n>/labels -f 'labels[]=…'`
- close: `gh api -X PATCH repos/{owner}/{repo}/issues/<n> -f state=closed`
- create PR: `gh api repos/{owner}/{repo}/pulls -f base=… -f head=… -f title=… -f body=… -F draft=true`
- merge PR: `gh api -X PUT repos/{owner}/{repo}/pulls/<n>/merge -f merge_method=merge`
The proxy also rejects remote branch deletion: leave merged branches on origin.
EOF

cat > ~/.claude/settings.json <<'EOF'
{
  "attribution": { "commit": "", "pr": "", "sessionUrl": false }
}
EOF
