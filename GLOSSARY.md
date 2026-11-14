# Agent PR pipeline

Skills that take a spec or PR from build through review and QA to merge, with as little human time as risk allows.

## Language

**Merge gate**:
The final check on a PR into base that either merges it or hands it to a human.
_Avoid_: auto-merge step, approval bot

**Verify gate**:
The repo's test command that a commit must pass before drive-spec pushes or merges it.
_Avoid_: CI, check

**Gate verdict**:
The verify gate's outcome for one commit: `green` or `red`.
_Avoid_: bare "verdict", pass/fail

**Risk tier**:
The merge gate's verdict on a PR: `auto` (may merge without a human) or `human` (needs a person's approval).
_Avoid_: risk level, low/medium/high

**Human path**:
A path whose change always puts a PR in the `human` tier, whatever else the PR touches.
_Avoid_: sensitive path, protected path

**Trusted author**:
A person or agent account whose PRs may be put in the `auto` tier.
_Avoid_: allowed author, whitelisted user

**Shadow mode**:
The merge gate deciding a risk tier and posting it without acting on it.
_Avoid_: dry run, audit mode

**Spec**:
An issue describing a feature, broken into tracer-bullet issues that drive-spec builds into one draft PR.
_Avoid_: epic, parent issue

**Slice**:
One tracer-bullet issue of a spec, built in its own worktree and merged into the spec branch.
_Avoid_: ticket, subtask, child issue

**Run**:
One spec driven by drive-spec from resolve to QA, across however many Claude sessions it takes; its status file is its whole picture.
_Avoid_: drive-spec session, job

**Agent**:
A detached Claude process a run launches for one slice: an implementer, or a merger on an integrate conflict.
_Avoid_: worker, subagent (a subagent lives inside the run's own session)
