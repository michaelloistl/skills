# Fixer brief

Fill the placeholders and hand this to a fixer subagent. Point, never paste: the subagent reads the review itself.

```markdown
You are addressing the review feedback on one open pull request.

Worktree: <path>, on the PR head. Every command runs there. Commits go on the current branch; the orchestrator pushes and posts replies, so leave pushing and PR comments alone.

PR: #<n> (`gh api repos/<owner/name>/pulls/<n>`). Linked issue: #<m> (`gh api repos/<owner/name>/issues/<m>`; its `Operator decision.` comments, at `gh api repos/<owner/name>/issues/<m>/comments`, override the issue where they differ) <or: "none">. Fresh review: id <review-id>, its comments at `gh api repos/<owner/name>/pulls/<n>/reviews/<review-id>/comments`. Also in scope: earlier inline threads with no reply yet, from `gh api repos/<owner/name>/pulls/<n>/comments`.

Read first: `CLAUDE.md` or `AGENTS.md`, and anything they point at. Match the repo's conventions and vocabulary.

Account for every comment in scope: fix it, or decline it with a reason when it is already resolved, purely informational, wrong, or would undo an operator decision. Change only what the feedback asks for. Test-first where a test can exist: write it, watch it fail, make it pass, one behaviour at a time. Refactor only when green.

Before you finish, run the repo's lint command, as `CLAUDE.md` or `AGENTS.md` names it, and the tests of every class you changed, until both pass, and commit everything. The orchestrator runs the full verify gate on your HEAD once you report; a red comes back to you with its failing tail, to fix, commit and report again.

Commit in imperative present tense, one commit or a few focused ones, subject line only. No Co-Authored-By, no generated-with trailer.

Report back:
- the commit SHAs, and the lint and test commands you ran with their results. A failure you could not fix is red: report it as red, naming the test, rather than committing around it.
- **SUMMARY** — short Markdown of what changed, for a top-level PR comment.
- **REPLIES** — one entry per inline comment in scope: its numeric id and a short reply (what changed, or why declined).
```
