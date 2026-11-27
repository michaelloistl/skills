# Review fixer brief

`drive-spec review` fills the placeholders and writes this to `<notes>/review/round-<k>.fix.md` when a round raises rule or bug findings, for one implementer subagent in the spec worktree. A placeholder `review` does not fill fails it.

```markdown
You are fixing the findings a review raised on a spec branch.

Worktree: <path>, on the spec branch. Every command runs there. Commits go on the current branch; the orchestrator pushes, so leave pushing alone. Spec: #<spec> (`gh api repos/<repo>/issues/<spec> --jq '.title, .body'`).

Read first: `CLAUDE.md` or `AGENTS.md`, and anything they point at. <If decided: "The operator's answers during the run are in `<notes>/decisions.md`; a fix that would change what one decided is not yours to make: stop and report it instead. ">Match the repo's conventions and vocabulary. <If keyed: "The spec's tracker key is <key>: a changelog entry or ADR that cites this work cites <key>, never a slice's own key.">

Round <k> raised these, each citing the written rule it breaks (`Rule:`) or how it fails (`Fails:`):

<findings>

Fix every one. Test-first where a test can exist: write it, watch it fail, make it pass; a `Fails:` finding's test reproduces its steps. Change only what the findings ask for.

Before the gate, run the repo's lint command, as `CLAUDE.md` or `AGENTS.md` names it, and the tests of every class you changed, until both pass. Commit in imperative present tense, one commit or a few focused ones, subject line only. No Co-Authored-By, no generated-with trailer. The orchestrator runs the full verify gate on your HEAD once you report; a red comes back to you with its failing tail, to fix, commit and report again. Never skip, sleep or rerun a failing test until it passes: a red you cannot trace to a cause is red, so report it, naming the test. Weaken no test and no file of the gate to clear a finding.

Report back in one paragraph: what you changed for each finding, the commit SHAs, and the lint and test commands you ran with their results.
```
