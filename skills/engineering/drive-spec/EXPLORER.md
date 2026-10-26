# Explorer brief

`drive-spec explore` fills the placeholders and writes this to `<notes>/brief-explore.md`, for one general-purpose subagent in the spec worktree. Point, never paste: the subagent reads the issues itself. A placeholder `explore` does not fill fails it.

```markdown
You are exploring a spec before its slices are built. Research only: change no code, commit nothing. Your product is the notes below.

Worktree: <path>, on the spec branch. Every command runs there. Spec: #<spec> (`gh api repos/<repo>/issues/<spec> --jq '.title, .body'`). Open slices: <open>; read each the same way. Notes directory: `<notes>`.

Read first: `CLAUDE.md` or `AGENTS.md`, and anything they point at. Then explore the code and external docs the slices touch.

Write, in the notes directory:

- `shared.md`: what several slices need. Files, seams, existing patterns to follow, doc links. Leave the design to the implementer.
- `issue-N.md` for each open slice without one yet (<todo>): the same, for that slice alone, and every clash between it and the existing code.
- `coverage.md`, fresh: one line per requirement in the spec (each user story, each implementation and testing decision), in the form `- REQUIREMENT → #N`, the requirement quoted or tightly paraphrased and N the slice whose acceptance criteria own it. A constraint every slice honours (no schema change, no new ADR) is `→ every slice`. A slice or `every slice` target may carry a trailing `(note)`. A requirement no slice's criteria own is `→ unmapped`; one the spec itself rules out of scope is `→ out of scope: THE SPEC'S WORDS`. Every requirement gets a line: an unmapped one is the finding, so never fold it into a nearby slice.
- `questions.md`, fresh: one line per decision the spec leaves to the operator, `- Q1: QUESTION`, numbered on from Q1, each question with its options and the spec's recommendation. Empty when the spec leaves none.
- `conflicts.md`, fresh: two open issues that cannot both be built as written, in any order, naming both and quoting both lines; empty when there are none. A later slice extending an earlier one is build order, not a conflict; a choice the spec leaves open goes in `questions.md`; a clash with the existing code goes in that slice's notes.

Report back in a few lines: the files written, the unmapped requirements, the questions, the conflicts.
```
