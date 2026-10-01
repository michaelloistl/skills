# Fixer brief

Fill the placeholders and hand this to a fixer subagent. Point, never paste: the subagent reads the review itself.

```markdown
You are addressing the review feedback on one open pull request.

Worktree: <path>, on the PR head. Every command runs there. Commits go on the current branch; the orchestrator pushes and posts replies, so leave pushing and PR comments alone.

PR: #<n> (`gh pr view <n>`). Linked issue: #<m> (`gh issue view <m>`) <or: "none">. Fresh review: id <review-id>, its comments at `gh api repos/{owner}/{repo}/pulls/<n>/reviews/<review-id>/comments`. Also in scope: earlier inline threads with no reply yet, from `gh api repos/{owner}/{repo}/pulls/<n>/comments`.

Read first: `CLAUDE.md` or `AGENTS.md`, and anything they point at. Match the repo's conventions and vocabulary.

Account for every comment in scope: fix it, or decline it with a reason when it is already resolved, purely informational, or wrong. Change only what the feedback asks for. Test-first where a test can exist: write it, watch it fail, make it pass, one behaviour at a time. Refactor only when green.

Verify gate, must be green before you finish: `<verify>`

Commit in imperative present tense, one commit or a few focused ones, subject line only. No Co-Authored-By, no generated-with trailer.

Report back:
- green or red, and the commit SHAs. Red means the verify gate is failing and why; report it as red rather than committing around it.
- **SUMMARY** — short Markdown of what changed, for a top-level PR comment.
- **REPLIES** — one entry per inline comment in scope: its numeric id and a short reply (what changed, or why declined).
```
