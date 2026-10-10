# Tracker

GitHub Issues via the REST API with `gh api`. Never `gh issue` or `gh pr`: they use GraphQL, which the cloud-session GitHub proxy rejects. The issue body format is a load-bearing contract, written by `/to-spec` and `/to-tickets`: headings at `##` level, `## Parent` holding the spec's `#<n>`, `## Blocked by` holding `#<m>` refs.

Resolve the repository once, at run start, as `owner/name` from the origin URL; `{owner}/{repo}` placeholders are not used because a cloud session's origin points at a proxy `gh` does not recognise.

```sh
repo=$(git remote get-url origin | sed -E 's#(\.git)?/*$##' | awk -F'[/:]' '{print $(NF-1)"/"$NF}')
```

REST reports state in lowercase: `open`, `closed`. The issues endpoints also return pull requests; drop any item with a `pull_request` key.

## Discovery

The spec is identified structurally: it has tracer-bullets and no `## Parent` section of its own. Nothing about its title or labels matters.

```sh
gh api "repos/$repo/issues/<spec>" --jq '{number,title,body,state}'
gh api --paginate "repos/$repo/issues?state=all&per_page=100" \
  --jq '.[] | select(.pull_request | not) | select((.body // "") | contains("#<spec>"))
        | {number,title,body,state,labels: [.labels[].name]}'
```

Listing and filtering locally, not the search endpoint: search indexes lag, and a ticket written seconds ago must be found.

A candidate is a tracer-bullet when the first `#N` in its `## Parent` section is the spec. Membership is textual only; a native sub-issue without `## Parent` is invisible to the run, so list it in the preview as invisible rather than building it.

## Blockers

The union of two sources, read for every slice:

- `## Blocked by` refs in the body.
- Native dependencies: `gh api "repos/$repo/issues/<m>/dependencies/blocked_by" --jq '.[].number'`.

For ordering, keep only blockers that are themselves slices of this spec; a blocker outside the spec is printed in the preview and otherwise ignored. A blocker that is still open gates the slice regardless of its source.

Topological order: repeatedly take the open or closed slice with every blocker already taken, lowest number first. Anything left over is a cycle: refuse, naming the slices in it.

## Slice state

| State | Evidence |
|---|---|
| closed | issue `state` is `closed` |
| open PR | `gh api "repos/$repo/pulls?state=open&base=<spec branch>&per_page=100" --jq '.[] \| select(.head.ref \| startswith("agent/issue-<m>-")) \| .number'` returns one |
| in-flight | `git ls-remote --heads origin 'agent/issue-<m>-*'` returns a branch and no open PR |
| todo | none of the above |

Check in that order: a closed slice's branch may linger on origin (see WORKTREES.md, Remove), and closed wins.

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

## Slice PRs

```sh
git push -u origin agent/issue-<m>-<slug>
gh api "repos/$repo/pulls" -f base=agent/local-spec-<n>-<slug> -f head=agent/issue-<m>-<slug> \
  -f title="<issue title>" -f body="Slice of #<spec>. Ref #<m>." --jq .number
```

`Ref`, never `Closes`: merging into a non-default branch would not auto-close, and the run closes the issue itself only after the merge is confirmed.

### Integration queue

Integrate one completed slice at a time. Implementers may continue in parallel, but the orchestrator is the sole writer advancing the spec branch.

For the slice at the head of the queue:

1. Push the slice and create its PR when absent.
2. Fetch origin in the slice worktree and record the current `origin/agent/local-spec-<n>-<slug>` SHA.
3. Merge that SHA into the slice branch. A conflicted merge goes to a merger subagent in the slice worktree; it resolves every conflict and commits the merge.
4. Run the verify gate unconditionally on the resulting HEAD, including when the merge was clean or already up to date. Red halts the run with the worktree intact.
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

Draft, `spec branch → base`, opened when the first slice lands; an open one already there is left as is. The body lists every slice in topological order, including those not yet built.

```sh
owner=${repo%/*}
gh api "repos/$repo/pulls?state=open&base=<base>&head=$owner:agent/local-spec-<n>-<slug>" \
  --jq '.[] | {number, url: .html_url}'
gh api "repos/$repo/pulls" -F draft=true -f base=<base> -f head=agent/local-spec-<n>-<slug> \
  -f title="<spec title>" -f body="$(cat <<'EOF'
Closes #<spec>

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
