# Fixer brief

Fill the placeholders and hand this to a fixer subagent. Point, never paste: the subagent reads the review itself.

```markdown
You are addressing the review feedback on one open pull request.

Worktree: <path>, on the PR head. Every command runs there. Commits go on the current branch; the orchestrator pushes and posts replies, so leave pushing and PR comments alone.

PR: #<n> (`gh api repos/<owner/name>/pulls/<n>`). Linked issue: #<m> (`gh api repos/<owner/name>/issues/<m>`) <or: "none">. Fresh review: id <review-id>, its comments at `gh api repos/<owner/name>/pulls/<n>/reviews/<review-id>/comments`. Also in scope: earlier inline threads with no reply yet, from `gh api repos/<owner/name>/pulls/<n>/comments`.

Read first: `CLAUDE.md` or `AGENTS.md`, and anything they point at. Match the repo's conventions and vocabulary.

Account for every comment in scope: fix it, or decline it with a reason when it is already resolved, purely informational, or wrong. Change only what the feedback asks for. Test-first where a test can exist: write it, watch it fail, make it pass, one behaviour at a time. Refactor only when green.

Verify gate, run once everything is committed, must print `green` before you finish: `<verify command>`. It runs the gate on your HEAD and records the verdict against that commit; the orchestrator checks that record before it pushes. It outlives the Bash timeout: start it with `run_in_background` and wait for its own completion notification. Its exit code is the verdict, so run it bare: no pipe and no command after it.

Commit in imperative present tense, one commit or a few focused ones, subject line only. No Co-Authored-By, no generated-with trailer.

Report back:
- the commit SHAs, and the verdict line the verify command printed, quoted verbatim (`green <sha>`, or `red <sha>: …`). No verdict line yet means the gate is still running: wait for its completion notification. Red means the verify gate is failing and why; report it as red rather than committing around it.
- **SUMMARY** — short Markdown of what changed, for a top-level PR comment.
- **REPLIES** — one entry per inline comment in scope: its numeric id and a short reply (what changed, or why declined).
```
