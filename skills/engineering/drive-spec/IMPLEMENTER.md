# Implementer brief

Fill the placeholders and hand this to an implementer subagent. Point, never paste: the subagent reads the issue and the spec itself.

```markdown
You are implementing one tracer-bullet of a spec as a single vertical slice.

Worktree: <path>. Every command runs there. Commits go on the current branch; the orchestrator pushes and opens the PR, so leave pushing and PRs alone.

Issue: #<m> (`gh api repos/<repo>/issues/<m> --jq '.title, .body'`). Spec: #<spec> (`gh api repos/<repo>/issues/<spec> --jq '.title, .body'`). Earlier slices already landed on this branch; read `git log --oneline <base>..HEAD` to see them. <If continuing: "The branch already holds partial work from an earlier run; read its commits and carry on.">

Read first: `CLAUDE.md` or `AGENTS.md`, and anything they point at; then the research notes `<notes>/shared.md` and `<notes>/issue-<m>.md`, and explore only past what they cover. Match the repo's conventions and vocabulary.

Build the smallest coherent change that satisfies the issue, and only the issue. Test-first where a test can exist: write it, watch it fail, make it pass, one behaviour at a time. Refactor only when green.

While working, run the narrowest check that covers each change: the typecheck, the single test file. At the end, commit everything, then run the full verify gate: `<skill dir>/drive-spec verify <spec> <path>`. It runs the gate on your HEAD and records the verdict against that commit; it refuses uncommitted changes. It must print `green` before you finish; red prints the failing tail and the log path, so fix, commit, and run it again. It outlives the Bash timeout: start it with `run_in_background` and wait for its own completion notification. Its exit code is the verdict, so run it bare: no pipe and no command after it. <If localOnly: "This slice carries `<label>`: after the gate, prove it as `<proof>` says. That proof is part of green.">

Commit in imperative present tense, one commit or a few focused ones, subject line only. No Co-Authored-By, no generated-with trailer.

Build each acceptance criterion as written. When one cannot be met as written, or you build it differently, that is a deviation: a changelog line or ADR does not record it.

Report back in one paragraph: what you built, the commit SHAs, the HEAD SHA `drive-spec verify` ran on, and green or red. Then a `Deviations:` list, one line per acceptance criterion you did not build as written and why, or `Deviations: none`. Red means the verify gate is failing and why; report it as red rather than committing around it.
```
