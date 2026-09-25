# Worktrees

Every branch the run touches is checked out in a worktree under one root. The checkout the session is standing in is read for config and nothing else.

## Root

```sh
common=$(git rev-parse --path-format=absolute --git-common-dir)   # the main repo's .git, even from inside a worktree
repo=$(dirname "$common")
root="$repo/.claude/worktrees"
grep -qx '.claude/worktrees/' "$common/info/exclude" || echo '.claude/worktrees/' >> "$common/info/exclude"
```

`worktreeRoot` in `.claude/implement-spec.json` overrides `root`.

## Names

| Thing | Branch | Worktree |
|---|---|---|
| spec | `agent/local-spec-<n>-<slug>` | `<root>/spec-<n>` |
| slice | `agent/issue-<m>-<slug>` | `<root>/issue-<m>` |

Slug: the issue title lowercased, runs of non-alphanumerics collapsed to `-`, trimmed, at most 40 characters. A branch already on origin keeps whatever slug it has; look it up with `git ls-remote --heads origin 'agent/local-spec-<n>-*'` rather than recomputing.

## Create

Always `git fetch --prune origin` first.

Spec, resume (branch on origin):

```sh
git worktree add "$root/spec-<n>" -B agent/local-spec-<n>-<slug> origin/agent/local-spec-<n>-<slug>
```

Spec, fresh:

```sh
git worktree add "$root/spec-<n>" -b agent/local-spec-<n>-<slug> origin/<base>
git -C "$root/spec-<n>" push -u origin agent/local-spec-<n>-<slug>
```

Pushing at once is what lets another session, or a later resume, see the spec is underway.

Slice, fresh, from the spec worktree's current HEAD:

```sh
git -C "$root/spec-<n>" pull --ff-only
git worktree add "$root/issue-<m>" -b agent/issue-<m>-<slug> agent/local-spec-<n>-<slug>
```

Slice, resume (branch on origin, with or without an open PR): same as spec resume with the slice names. Restore the worktree before continuing implementation or entering the integration queue.

A path that already exists is reused when it is on the expected branch, and is an error otherwise. A branch checked out in a worktree the run did not create belongs to another session: stop and say which path holds it.

## Bootstrap

Run `bootstrap` from the config in every new worktree, from that worktree's directory. A non-zero exit fails the run before any agent starts. Absent config means no bootstrap step.

## Remove

After a slice lands:

```sh
git worktree remove --force "$root/issue-<m>"
git branch -D agent/issue-<m>-<slug>
git push origin --delete agent/issue-<m>-<slug>
```

After the final PR opens: remove the spec worktree the same way but keep the branch, local and remote, until the PR merges.

On halt: keep the slice worktree in place so the developer can look, and print its path.

Finish every run, including a halt, with `git worktree prune`.
