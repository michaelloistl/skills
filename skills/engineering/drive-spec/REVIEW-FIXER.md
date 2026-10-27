# Review fixer brief

`drive-spec review` fills the placeholders and writes this to `<notes>/review/round-<k>.fix.md` when a round raises rule or bug findings, for one implementer subagent in the spec worktree. A placeholder `review` does not fill fails it.

```markdown
You are fixing the findings a review raised on a spec branch.

Worktree: <path>, on the spec branch. Every command runs there. Commits go on the current branch; the orchestrator pushes, so leave pushing alone. Spec: #<spec> (`gh api repos/<repo>/issues/<spec> --jq '.title, .body'`).

Read first: `CLAUDE.md` or `AGENTS.md`, and anything they point at. <If decided: "The operator's answers during the run are in `<notes>/decisions.md`; a fix that would change what one decided is not yours to make: stop and report it instead. ">Match the repo's conventions and vocabulary.

Round <k> raised these, each citing the written rule it breaks (`Rule:`) or how it fails (`Fails:`):

<findings>

Fix every one. Test-first where a test can exist: write it, watch it fail, make it pass; a `Fails:` finding's test reproduces its steps. Change only what the findings ask for.

Before the gate, run the repo's lint command, as `CLAUDE.md` or `AGENTS.md` names it, and the tests of every class you changed, until both pass. Commit in imperative present tense, one commit or a few focused ones, subject line only. No Co-Authored-By, no generated-with trailer. Then run the verify gate: `<skill dir>/drive-spec verify <spec> <path> --wait-minutes 9`, in the foreground with a 10-minute Bash timeout. Exit 6 prints `running …`: the gate goes on, so run the same command again until it prints a verdict. Its exit code is the verdict, so run it bare: no pipe and no command after it. Red: fix, commit, verify again.

Report back in one paragraph: what you changed for each finding, the commit SHAs, and the verdict line `drive-spec verify` printed, quoted verbatim (`green SHA` or `red SHA: …`).
```
