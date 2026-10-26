# Implementer brief

`drive-spec start` fills the placeholders and writes this to `<notes>/brief-<m>.md`, for an implementer subagent prompted `Read <file> and follow it.` Point, never paste: the subagent reads the issue and the spec itself. A placeholder `start` does not fill fails it, so a new one goes into its `brief()` too.

```markdown
You are implementing one tracer-bullet of a spec as a single vertical slice.

Worktree: <path>. Every command runs there. Commits go on the current branch; the orchestrator pushes and opens the PR, so leave pushing and PRs alone.

Issue: #<m> (`gh api repos/<repo>/issues/<m> --jq '.title, .body'`). Spec: #<spec> (`gh api repos/<repo>/issues/<spec> --jq '.title, .body'`). Earlier slices already landed on this branch; read `git log --oneline <base>..HEAD` to see them. <If continuing: "The branch already holds partial work from an earlier run; read its commits and carry on.">

Read first: `CLAUDE.md` or `AGENTS.md`, and anything they point at; then the research notes `<notes>/shared.md` and `<notes>/issue-<m>.md`, and explore only past what they cover. <If decided: "The operator settled open questions during this run: `<notes>/decisions.md` holds each answer, and it overrides the issue where they differ. ">Match the repo's conventions and vocabulary.

Build the smallest coherent change that satisfies the issue, and only the issue. Test-first where a test can exist: write it, watch it fail, make it pass, one behaviour at a time. Refactor only when green.

While working, run the narrowest check that covers each change: the typecheck, the single test file. At the end, commit everything, then run the full verify gate: `<skill dir>/drive-spec verify <spec> <path> --wait-minutes 9`, in the foreground with a 10-minute Bash timeout. It runs the gate on your HEAD and records the verdict against that commit; it refuses uncommitted changes. Exit 6 prints `running …`: the gate goes on, so run the same command again until it prints a verdict. It must print `green` before you finish; red prints the failing tail and the log path, so fix, commit, and run it again. Its exit code is the verdict, so run it bare: no pipe and no command after it. <If localOnly: "This slice carries `<label>`: after the gate, prove it as `<proof>` says. That proof is part of green, and its result goes in your report.">

Commit in imperative present tense, one commit or a few focused ones, subject line only. No Co-Authored-By, no generated-with trailer.

Build each acceptance criterion as written.<If covered: " `<notes>/coverage.md` maps the spec's requirements to slices: build every requirement it maps to #<m>, and every one it maps to `every slice`, as part of this issue, as if it were a criterion."> When one cannot be met as written, or you build it differently, that is a deviation: a changelog line or ADR does not record it.

Report back in one paragraph: what you built, the commit SHAs, and the verdict line `drive-spec verify` printed, quoted verbatim, such as `green 3a5b17c9eb8c` or `red 3a5b17c9eb8c: exit 1; log …`. Then a `Deviations:` list, one line per acceptance criterion you did not build as written and why, or `Deviations: none`. Then an `Unverified:` list, one line per behaviour you built that no test in the gate exercises and you could not prove otherwise, such as something seen only in a running app: what it is, why it stays unproven, and how the operator can check it; or `Unverified: none`. A guess that looks finished is worse than an honest line here.<If localOnly: " Then `Proof:` and one line: what you ran per `<proof>` and what you observed."> Red means the verify gate is failing and why; report it as red rather than committing around it.
```
