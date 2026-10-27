# Agent PR pipeline

Skills that take a spec or PR from build through review and QA to merge, with as little human time as risk allows.

## Language

**Merge gate**:
The final check on a PR into base that either merges it or hands it to a human.
_Avoid_: auto-merge step, approval bot

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
