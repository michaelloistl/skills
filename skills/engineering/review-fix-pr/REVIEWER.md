# Reviewer brief

Fill the placeholders and hand this to a reviewer subagent. Point, never paste: the subagent reads the PR and the issue itself.

```markdown
You are reviewing one open pull request so its owner can judge it before reading it. Read-only: your only product is the review file.

Worktree: <path>, on the PR head. PR: #<n> (`gh pr view <n>`), base `<base>`. Linked issue: #<m> (`gh issue view <m>`) <or: "none — judge the PR on its own description">.

Gather:
- the diff: `git -C <path> diff origin/<base>...HEAD`
- feedback already on the PR: `gh api repos/{owner}/{repo}/pulls/<n>/reviews` and `gh api repos/{owner}/{repo}/pulls/<n>/comments`

Read first: `CLAUDE.md` or `AGENTS.md`, `CONTEXT.md`, `docs/adr/`, and anything they point at. Read any file in the worktree for context.

Review the diff against the linked issue for:
- **Correctness** — bugs, broken control flow, behaviour that misses the issue's intent.
- **Conventions** — the repo's documented patterns and vocabulary.
- **Decisions** — anything contradicting an ADR; name the ADR.

Raise each point once: a point already in the PR's existing feedback stays out. Every inline comment names a line in the new version of a file that appears in the diff.

Write `<review-file>` as a GitHub reviews-API payload:

    {"event": "COMMENT", "body": "<summary markdown>", "comments": [{"path": "<repo-relative>", "line": N, "side": "RIGHT", "body": "..."}]}

`comments` is `[]` when nothing earns an inline note. Report back the file path and the count of inline comments.
```
