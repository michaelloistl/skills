# Explorer brief

`drive-spec explore` fills the placeholders and writes this to `<notes>/brief-explore.md`, for one general-purpose subagent in the spec worktree. Point, never paste: the subagent reads the issues itself. A placeholder `explore` does not fill fails it.

```markdown
You are exploring a spec before its slices are built. Research only: change no code, commit nothing. Your product is the notes below.

Worktree: <path>, on the spec branch. Every command runs there. Spec: #<spec> (`gh api repos/<repo>/issues/<spec> --jq '.title, .body'`). Open slices: <open>; read each from the run's issue cache, `jq -r '.issues["N"] | .title, .body' <notes>/issues.json`, which holds every slice. Notes directory: `<notes>`.

Read first: `CLAUDE.md` or `AGENTS.md`, and anything they point at. Then explore the code and external docs the slices touch.

Write, in the notes directory:

- `shared.md`: what several slices need. Files, seams, existing patterns to follow, doc links. Leave the design to the implementer.
- `issue-N.md` for each open slice without one yet (<todo>): the same, for that slice alone, and every clash between it and the existing code.
- In both, under `## ADRs`, every ADR whose subject the slices change, by path, with the decisions and amendments that bind them. List the repo's ADR titles and judge each one: the title, not the code you happened to read, is the test.
- `coverage.md`, fresh: one line per requirement in the spec (each user story, each implementation and testing decision), in the form `- REQUIREMENT → #N`, the requirement quoted or tightly paraphrased and N the slice whose acceptance criteria own it. A constraint every slice honours (no schema change, no new ADR) is `→ every slice`. Several slices sharing one is `→ #N (note) and #M (note)`. A slice or `every slice` target may carry a trailing `(note)`. A requirement no slice's criteria own is `→ unmapped`; one the spec itself rules out of scope is `→ out of scope: THE SPEC'S WORDS`; one the base branch already meets is `→ done on base: WHERE`. Every requirement gets a line: an unmapped one is the finding, so never fold it into a nearby slice. Only `- ` lines are read; a heading or a summary sentence is skipped. For example:

      - Export a report to CSV → #11
      - Route at /reports/export → #12 (route) and #11 (serializer)
      - No schema change → every slice
      - PDF export → out of scope: "PDF stays out of this spec"

- `questions.md`, fresh: one line per decision the spec leaves to the operator, `- Q1: QUESTION`, numbered on from Q1, each question with its options and the recommendation, the spec's where it gives one, with its reason. A spec or slice line that contradicts an ADR, an amendment included, is one too: quote both, and give amending the ADR and changing the spec as options. Empty when the spec leaves none.
- `conflicts.md`, fresh: two open issues that cannot both be built as written, in any order, naming both by number (`#12`) and quoting both lines, then a `Recommend:` line saying which line you would change and why; empty, or the one word `none`, when there are none. A later slice extending an earlier one is build order, not a conflict; a choice the spec leaves open goes in `questions.md`; a clash with the existing code goes in that slice's notes.

Then run `<skill dir>/drive-spec explored <spec> --check`, which records and posts nothing: it names each note missing or out of form. Done when it exits 0.

Report back one line and nothing else: `explored: N slice notes, N ADRs, N unmapped, N questions, N conflicts`. The notes hold the rest; the orchestrator reads them only when a command names one.
```
