# Implementer brief

Fill the placeholders and hand this to an implementer subagent. Point, never paste: the subagent reads the issue and the spec itself.

```markdown
You are implementing one tracer-bullet of a spec as a single vertical slice.

Worktree: <path>. Every command runs there. Commits go on the current branch; the orchestrator pushes and opens the PR, so leave pushing and PRs alone.

Issue: #<m> (`gh issue view <m>`). Spec: #<spec> (`gh issue view <spec>`). Earlier slices already landed on this branch; read `git log --oneline <base>..HEAD` to see them. <If continuing: "The branch already holds partial work from an earlier run; read its commits and carry on.">

Read first: `CLAUDE.md` or `AGENTS.md`, and anything they point at. Match the repo's conventions and vocabulary.

Build the smallest coherent change that satisfies the issue, and only the issue. Test-first where a test can exist: write it, watch it fail, make it pass, one behaviour at a time. Refactor only when green.

Verify gate, must be green before you finish: `<verify>`

Commit in imperative present tense, one commit or a few focused ones, subject line only. No Co-Authored-By, no generated-with trailer.

Report back in one paragraph: what you built, the commit SHAs, and green or red. Red means the verify gate is failing and why; report it as red rather than committing around it.
```
