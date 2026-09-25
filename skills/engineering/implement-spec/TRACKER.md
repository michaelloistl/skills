# Tracker

GitHub Issues via `gh`. The issue body format is a load-bearing contract, written by `/to-spec` and `/to-tickets`: headings at `##` level, `## Parent` holding the spec's `#<n>`, `## Blocked by` holding `#<m>` refs.

## Discovery

The spec is identified structurally: it has tracer-bullets and no `## Parent` section of its own. Nothing about its title or labels matters.

```sh
gh issue view <spec> --json number,title,body,state
gh issue list --state all --limit 200 --search "\"#<spec>\" in:body" \
  --json number,title,body,state,labels
```

A candidate is a tracer-bullet when the first `#N` in its `## Parent` section is the spec. Membership is textual only; a native sub-issue without `## Parent` is invisible to the run, so list it in the preview as invisible rather than building it.

## Blockers

The union of two sources, read for every slice:

- `## Blocked by` refs in the body.
- Native dependencies: `gh api repos/{owner}/{repo}/issues/<m>/dependencies/blocked_by --jq '.[].number'`.

For ordering, keep only blockers that are themselves slices of this spec; a blocker outside the spec is printed in the preview and otherwise ignored. A blocker that is still open gates the slice regardless of its source.

Topological order: repeatedly take the open or closed slice with every blocker already taken, lowest number first. Anything left over is a cycle: refuse, naming the slices in it.

## Slice state

| State | Evidence |
|---|---|
| closed | issue state is `CLOSED` |
| open PR | `gh pr list --state open --base <spec branch> --head agent/issue-<m>-* --json number,mergeable` returns one |
| in-flight | `git ls-remote --heads origin 'agent/issue-<m>-*'` returns a branch and no open PR |
| todo | none of the above |

## Labels

Created on first use, never assumed:

```sh
gh label create agent:in-progress --color 0E8A16 --force
gh label create agent:blocked --color B60205 --force
```

`agent:in-progress` goes on when the implementer is dispatched and comes off when the issue closes. `agent:blocked` goes on with a comment when a slice halts the run, and the operator removes it after fixing.

## Progress comment

One comment on the spec issue, found by the marker and edited in place with `gh api --method PATCH repos/{owner}/{repo}/issues/comments/<id>`; created with `gh issue comment` when absent.

```markdown
<!-- implement-spec -->
**Building `agent/local-spec-<n>-<slug>` → `<base>`**

- [x] #12 Create the serializer
- [ ] #13 Wire the export route ← building
- [ ] #14 Add the download button

_Updated <ISO timestamp> from <hostname>._
```

Every slice in topological order; closed slices ticked; the one in flight marked. When the final PR exists, a last line names it.

## Slice PRs

```sh
git push -u origin agent/issue-<m>-<slug>
gh pr create --base agent/local-spec-<n>-<slug> --head agent/issue-<m>-<slug> \
  --title "<issue title>" --body "Slice of #<spec>. Ref #<m>."
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
6. Merge the PR only after GitHub reports it mergeable, then confirm `mergedAt` is non-null. A queued or blocked merge is not landed.

```sh
git -C <slice-worktree> fetch origin
integrated_spec=$(git -C <slice-worktree> rev-parse origin/agent/local-spec-<n>-<slug>)
git -C <slice-worktree> merge --no-edit "$integrated_spec"
<verify>
git -C <slice-worktree> push origin agent/issue-<m>-<slug>
git -C <slice-worktree> fetch origin
current_spec=$(git -C <slice-worktree> rev-parse origin/agent/local-spec-<n>-<slug>)
# Repeat merge and verify unless "$current_spec" = "$integrated_spec".
gh pr view <pr> --json mergeable,mergedAt
gh pr merge <pr> --merge
gh pr view <pr> --json mergedAt
gh issue close <m> --comment "Landed in #<pr> on \`agent/local-spec-<n>-<slug>\`."
```

Pull the spec worktree and finish the slice's land and cleanup steps before taking the next queue entry. Branches still owned by active implementers stay untouched until they enter the queue.

## Final PR

```sh
gh pr list --state open --base <base> --head agent/local-spec-<n>-<slug> --json number,url
gh pr create --draft --base <base> --head agent/local-spec-<n>-<slug> \
  --title "<spec title>" --body "$(cat <<'EOF'
Closes #<spec>

Slices, in build order:
- #12 Create the serializer
- #13 Wire the export route
- #14 Add the download button
EOF
)"
```

## Halting

```sh
gh issue edit <m> --add-label agent:blocked --remove-label agent:in-progress
gh issue comment <m> --body "implement-spec halted here: <one line why>. Worktree kept at <path>. Resume with \`/implement-spec <spec>\` after fixing."
```
