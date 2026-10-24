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

Created on first use, never assumed. The colon is URL-encoded in paths:

```sh
gh api "repos/$repo/labels/agent%3Ain-progress" --silent 2>/dev/null \
  || gh api "repos/$repo/labels" -f name=agent:in-progress -f color=0E8A16 --silent
gh api "repos/$repo/labels/agent%3Ablocked" --silent 2>/dev/null \
  || gh api "repos/$repo/labels" -f name=agent:blocked -f color=B60205 --silent
```

Add and remove:

```sh
gh api "repos/$repo/issues/<m>/labels" -f 'labels[]=agent:in-progress' --silent
gh api -X DELETE "repos/$repo/issues/<m>/labels/agent%3Ain-progress" --silent
```

`agent:in-progress` goes on when the implementer is dispatched and comes off when the issue closes. `agent:blocked` goes on with a comment when a slice halts the run, and the operator removes it after fixing.

## Progress comment

One comment on the spec issue, found by the marker and edited in place; created when absent.

```sh
id=$(gh api --paginate "repos/$repo/issues/<spec>/comments" \
  --jq '.[] | select(.body | startswith("<!-- implement-spec -->")) | .id' | head -1)
# absent:
gh api "repos/$repo/issues/<spec>/comments" -f body="$body" --silent
# present:
gh api -X PATCH "repos/$repo/issues/comments/$id" -f body="$body" --silent
```

```markdown
<!-- implement-spec -->
**Building `agent/local-spec-<n>-<slug>` → `<base>`**

- [x] #12 Create the serializer
- [ ] #13 Wire the export route ← building
- [ ] #14 Add the download button
- [ ] #15 Check the export in the desktop app ← held for a local run

_Updated <ISO timestamp> from <hostname>._
```

Every slice in topological order; closed slices ticked; the one in flight marked; held slices marked. When the spec PR exists, a last line names it.

## Status comment

A fresh comment on the spec issue as the run's last action, never an edit: edits notify no one, and this comment is how the operator learns the run is over. The first line is the outcome; every outcome but done adds the resume command on a second line.

```sh
gh api "repos/$repo/issues/<spec>/comments" --silent -f body="$body"
```

| Outcome | First line |
|---|---|
| done | `drive-spec done: all <k> slices landed, review clean. Spec PR #<pr>.` |
| halted | `drive-spec halted on #<m>: <one line why>.` |
| conflicts | `drive-spec halted before building: the spec and its slices disagree.` followed by the list from `conflicts.md` |
| ceiling | `drive-spec paused at maxSlices: <landed> of <k> slices landed.` |
| held | `drive-spec paused: only held slices remain (#<m>, …). Resume in a local session.` |

## Slice PRs

```sh
git push -u origin agent/issue-<m>-<slug>
gh api "repos/$repo/pulls" -f base=agent/local-spec-<n>-<slug> -f head=agent/issue-<m>-<slug> \
  -f title="<issue title>" -f body="Slice of #<spec>. Ref #<m>.

<the implementer's Deviations list>" --jq .number
```

`Ref`, never `Closes`: merging into a non-default branch would not auto-close, and the run closes the issue itself only after the merge is confirmed.

### Integration queue

Integrate one completed slice at a time. Implementers may continue in parallel, but the orchestrator is the sole writer advancing the spec branch.

For the slice at the head of the queue:

1. Push the slice and create its PR when absent.
2. Fetch origin in the slice worktree and record the current `origin/agent/local-spec-<n>-<slug>` SHA.
3. Merge that SHA into the slice branch. A conflicted merge goes to a merger subagent in the slice worktree; it resolves every conflict and commits the merge.
4. Run the verify gate on the resulting HEAD, including when the merge was clean. Skip it only when HEAD is still the SHA the implementer reported green: that exact tree is already verified. Red halts the run with the worktree intact.
5. Push the slice branch. Fetch origin again; when the spec branch SHA differs from the recorded SHA, return to step 2.
6. Merge the PR only after GitHub reports it mergeable, then confirm `merged_at` is non-null. `mergeable` reads `null` while GitHub computes it: wait a few seconds and read again. A queued or blocked merge is not landed.

```sh
git -C <slice-worktree> fetch origin
integrated_spec=$(git -C <slice-worktree> rev-parse origin/agent/local-spec-<n>-<slug>)
git -C <slice-worktree> merge --no-edit "$integrated_spec"
<verify>
git -C <slice-worktree> push origin agent/issue-<m>-<slug>
git -C <slice-worktree> fetch origin
current_spec=$(git -C <slice-worktree> rev-parse origin/agent/local-spec-<n>-<slug>)
# Repeat merge and verify unless "$current_spec" = "$integrated_spec".
gh api "repos/$repo/pulls/<pr>" --jq '{mergeable, merged_at}'
gh api -X PUT "repos/$repo/pulls/<pr>/merge" -f merge_method=merge --silent
gh api "repos/$repo/pulls/<pr>" --jq .merged_at
gh api "repos/$repo/issues/<m>/comments" \
  -f body="Landed in #<pr> on \`agent/local-spec-<n>-<slug>\`." --silent
gh api -X PATCH "repos/$repo/issues/<m>" -f state=closed -f state_reason=completed --silent
```

Pull the spec worktree and finish the slice's land and cleanup steps before taking the next queue entry. Branches still owned by active implementers stay untouched until they enter the queue.

## Spec PR

Draft, `spec branch → base`, opened when the first slice lands; an open one already there is left as is. The body lists every slice in topological order, including those not yet built. It says `Ref #<spec>` while any slice is open, so merging the draft early cannot close the spec; step 8 changes it to `Closes #<spec>`.

```sh
owner=${repo%/*}
gh api "repos/$repo/pulls?state=open&base=<base>&head=$owner:agent/local-spec-<n>-<slug>" \
  --jq '.[] | {number, url: .html_url}'
gh api "repos/$repo/pulls" -F draft=true -f base=<base> -f head=agent/local-spec-<n>-<slug> \
  -f title="<spec title>" -f body="$(cat <<'EOF'
Ref #<spec>

Slices, in build order:
- #12 Create the serializer
- #13 Wire the export route
- #14 Add the download button
EOF
)" --jq .html_url
```

## Halting

```sh
gh api "repos/$repo/issues/<m>/labels" -f 'labels[]=agent:blocked' --silent
gh api -X DELETE "repos/$repo/issues/<m>/labels/agent%3Ain-progress" --silent
gh api "repos/$repo/issues/<m>/comments" --silent \
  -f body="drive-spec halted here: <one line why>. Worktree kept at <path>. Resume with \`/drive-spec <spec>\` after fixing."
```
