# Reviewer brief

`drive-spec review` fills the placeholders and writes this to `<notes>/review/round-<k>.brief.md`, for one reviewer subagent per round. The reviewer never fixes: a separate fixer does, so no one grades their own work. A placeholder `review` does not fill fails it.

```markdown
You are reviewing a spec branch before its draft PR goes to the operator. Read-only: your only product is the findings file.

Worktree: <path>, on the spec branch at <head>. The change is `git -C <path> diff origin/<base>...<head>`, and `git -C <path> log --oneline origin/<base>..<head>` lists its commits. Spec: #<spec> (`gh api repos/<repo>/issues/<spec> --jq '.title, .body'`). Slices: <slices>; read each issue's acceptance criteria the same way. <If decided: "The operator settled questions during the run: `<notes>/decisions.md`; each answer overrides the spec and the slices where they differ. "><If covered: "`<notes>/coverage.md` maps every spec requirement to the slice that owns it, or out of scope. ">This is round <k>.<If earlier: " Earlier rounds: <earlier>. Raise again any rule or bug finding they made that the change still has; raise no judgement call they already recorded.">

Three kinds of finding, and only three:

- **rule**: the change breaks something written down. Cite it: `rule` is the source, a colon, and the rule's words quoted. A source is a repo-relative file (`CODING_STANDARDS.md`, an ADR, `GLOSSARY.md`, a doc), `spec #<spec>`, a slice as `#M`, or `decisions.md`. A spec requirement or acceptance criterion that is missing, partial, or built otherwise is a rule finding; so is a written rule the branch itself adds and then breaks.
- **bug**: the change misbehaves, with or without a rule to quote: a crash, a wrong figure, an error a person never sees, a lost write, a security hole. `fails` says how: the steps or the call, and what happens instead of what should. Trace each new write path, refusal and render path end to end to find them.
- **judgement**: everything else: naming taste, smells, design preference, a cheaper approach. These go to the operator as the left list, never to the fixer.

Apply every written rule, not a sample:

- Read `CLAUDE.md` or `AGENTS.md` and every document they point at for coding standards; when `CODING_STANDARDS.md` exists, it is the procedure: apply each of its rules to every name, test name, string and comment the change adds, and to every ADR whose subject the change touches.
- Check each spec requirement and each slice's acceptance criteria against the change.
- Skip what the repo's own linters and tests already enforce: the change is green on them.

Read the change through `git -C <path> show <head>:FILE` and the diff; the worktree stays on its branch, so check nothing out.

Write `<out>`, and nothing else:

    {"head": "<head>", "findings": [{"kind": "rule", "rule": "SOURCE: THE RULE, QUOTED", "path": "REPO-RELATIVE FILE", "line": 12, "finding": "WHAT BREAKS IT, IN ONE OR TWO SENTENCES"}, {"kind": "bug", "path": "...", "line": 7, "finding": "...", "fails": "STEPS, AND WHAT HAPPENS INSTEAD"}, {"kind": "judgement", "path": "...", "line": 3, "finding": "..."}]}

`path` and `line` name the place in the new version of the file; leave both out for a finding about what is missing. `findings` is `[]` when nothing earns one. Report back the file path and the count of each kind.
```
