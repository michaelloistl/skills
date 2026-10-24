# Tracker

GitHub Issues via the REST API with `gh api`. Never `gh issue` or `gh pr`: they use GraphQL, which the cloud-session GitHub proxy rejects. The issue body format is a load-bearing contract, written by `/to-spec` and `/to-tickets`: headings at `##` level, `## Parent` holding the spec's `#<n>`, `## Blocked by` holding `#<m>` refs.

Resolve the repository once, at run start, as `owner/name` from the origin URL; `{owner}/{repo}` placeholders are not used because a cloud session's origin points at a proxy `gh` does not recognise.

```sh
repo=$(git remote get-url origin | sed -E 's#(\.git)?/*$##' | awk -F'[/:]' '{print $(NF-1)"/"$NF}')
```

REST reports state in lowercase: `open`, `closed`. The issues endpoints also return pull requests; drop any item with a `pull_request` key.

## Discovery, blockers and slice state

`drive-spec plan <spec>` computes all three; this section is the contract it implements, and `test_drive_spec.py` holds it to it.

- **Spec**: identified structurally: it has tracer-bullets and no `## Parent` of its own. Title and labels do not matter.
- **Discovery** lists every issue and filters locally, never the search endpoint: search indexes lag, and a ticket written seconds ago must be found.
- **Membership**: a slice is an issue whose first `#N` under `## Parent` is the spec. Textual only: a native sub-issue without `## Parent` is printed as invisible and never built.
- **Blockers**: the `#<m>` refs under `## Blocked by`. Only blockers that are slices of this spec order the build; any other is printed and ignored.
- **Order**: repeatedly take the slice, open or closed, whose blockers are all taken, lowest number first. Anything left over is a cycle: refuse, naming only the slices on it.
- **State**, first match wins: `closed` (issue closed; a closed slice's branch may linger on origin, see WORKTREES.md, Remove); `held` (a cloud session and the `localOnly` label); `open-pr` (an open PR into the spec branch from `agent/issue-<m>-*`); `in-flight` (that branch on origin, no PR); `todo`.
- A failed tracker or git call fails the plan loudly, never an empty plan: an empty one would refuse the spec for the wrong reason.

## Labels

Created on first use, never assumed. `agent:in-progress` (green) goes on in `drive-spec start` and comes off in `drive-spec land` or `drive-spec halt`. `agent:blocked` (red) goes on in `drive-spec halt`; the operator removes it after fixing, and until then `frontier` and `start` refuse to go on.

## Progress comment

One comment on the spec issue, found by its marker and edited in place, created when absent. `drive-spec progress <spec>` writes it, and `drive-spec land` refreshes it after every landing.

```markdown
<!-- implement-spec -->
**Building `agent/local-spec-<n>-<slug>` → `<base>`**

- [x] #12 Create the serializer
- [ ] #13 Wire the export route ← building
- [ ] #14 Add the download button
- [ ] #15 Check the export in the desktop app ← held for a local run

Spec PR: #<pr>

_Updated <ISO timestamp> from <hostname>._
```

Every slice in build order; closed slices ticked; `← building` on open slices labelled `agent:in-progress`; held slices marked; the spec PR line once it exists.

## Status comment

A fresh comment on the spec issue as the run's last action, never an edit: edits notify no one, and this comment is how the operator learns the run is over. `drive-spec finish <spec> <outcome>` posts it, refreshes the progress comment, and writes the final status; `drive-spec halt` finishes as `halted`. The first line is the outcome; every outcome but done adds the resume command (default `/drive-spec <spec>`, else `--resume`) on a second line.

| Outcome | First line | Refused when |
|---|---|---|
| done | `drive-spec done: all <k> slices landed, review clean. Spec PR #<pr>.` | a slice is open, or no spec PR is |
| halted | `drive-spec halted on #<m>: <why>.`, or without a slice `drive-spec halted: <why>.` | no `--why` |
| conflicts | `drive-spec halted before building: the spec and its slices disagree.`, then the list from `conflicts.md` | `conflicts.md` is empty |
| ceiling | `drive-spec paused at maxSlices: <landed> of <k> slices landed.` | |
| held | `drive-spec paused: only held slices remain (#<m>, …). Resume in a local session.` | no slice is held |
| refused | `drive-spec refused #<spec>: <the plan's refuse line>.` | the plan does not refuse |

## Integration and landing

`drive-spec integrate <spec> <m>` and `drive-spec land <spec> <m>`; this is the contract they implement, held by `test_drive_spec.py`.

- **Verdicts**: `drive-spec verify <spec> <worktree>` runs the run's gate (pinned with `drive-spec gate`, else `verify` from `.claude/drive-spec.json`) on a clean worktree's HEAD, under `flock /tmp/drive-spec-verify.lock` when `flock` exists, so every drive-spec on the machine queues for the full suite. It records the verdict against that commit in the notes directory. Only a green record lets a commit merge; an implementer's claim never does. A commit already green is not run again.
- **One at a time**: integrate holds a lock per spec, so the orchestrator stays the sole writer advancing the spec branch. Implementers may keep building in parallel.
- **Refusals**, exit 2: a dirty worktree, a merge in progress, a commit with a body or trailer (subject line only), or a new PR without `--deviations`.
- **Slice PR**: `slice branch → spec branch`, titled after the issue, body `Slice of #<spec>. Ref #<m>.` and the implementer's `Deviations:` list. `Ref`, never `Closes`: merging into a non-default branch would not auto-close, and land closes the issue only after the merge is confirmed.
- **Loop**: fetch, record the spec branch SHA, merge it into the slice, verify, push. When the spec branch moved meanwhile, go again. A conflict aborts the merge and exits 3, naming the SHA and files for a merger subagent. Red exits 4 with the worktree intact.
- **Merge**: only after GitHub computes `mergeable` (it reads `null` until then) on exactly the verified HEAD, and with that SHA pinned in the merge call, so a branch that moved underneath cannot merge. `merged_at` must then be set: a queued or blocked merge is not landed.
- **Land**: refuses a slice with no merged PR. Then pulls the spec worktree, comments `Landed in #<pr> on \`<spec branch>\`.` and closes the issue, removes `agent:in-progress`, removes the slice worktree and local branch, and deletes the remote branch unless a cloud session's proxy forbids it or the repo already deleted it. Running it again finishes whatever a failed run left.

## Spec PR

Draft, `spec branch → base`, opened by `drive-spec land` when the first slice lands; an open one already there is left as is. Base comes from the status file, then `baseBranch` in `.claude/drive-spec.json`, then the repo's default branch. The body lists every slice in build order, including those not yet built. It says `Ref #<spec>` while any slice is open, so merging the draft early cannot close the spec; step 8 changes it to `Closes #<spec>`:

```sh
owner=${repo%/*}
gh api "repos/$repo/pulls?state=open&base=<base>&head=$owner:agent/local-spec-<n>-<slug>" \
  --jq '.[] | {number, body, url: .html_url}'
gh api -X PATCH "repos/$repo/pulls/<pr>" -f body="$body" --silent
```

## Halting

`drive-spec halt <spec> <m> <why>`: labels the slice `agent:blocked`, removes `agent:in-progress`, comments `drive-spec halted here: <why>. Worktree kept at <path>. Resume with \`/drive-spec <spec>\` after fixing.` on it, then finishes the run as `halted`.
