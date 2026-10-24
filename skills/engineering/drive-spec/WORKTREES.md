# Worktrees

Every branch the run touches is checked out in a worktree under one root. The checkout the session is standing in is read for config and nothing else.

## Root

```sh
common=$(git rev-parse --path-format=absolute --git-common-dir)   # the main repo's .git, even from inside a worktree
repo=$(dirname "$common")
root="$repo/.claude/worktrees"
grep -qx '.claude/worktrees/' "$common/info/exclude" || echo '.claude/worktrees/' >> "$common/info/exclude"
```

`worktreeRoot` in `.claude/drive-spec.json` overrides `root`.

## Notes

Research notes for spec `<n>` live in `$common/drive-spec/spec-<n>/`: inside the shared git dir, so every worktree and every session reaches the same files, and outside every working tree, so nothing gets committed. They survive a halt, so a resume reuses them.

## Names

| Thing | Branch | Worktree |
|---|---|---|
| spec | `agent/local-spec-<n>-<slug>` | `<root>/spec-<n>` |
| slice | `agent/issue-<m>-<slug>` | `<root>/issue-<m>` |

Slug: compute it, never type it.

```sh
slug=$(gh api "repos/$repo/issues/<issue>" --jq .title | tr 'A-Z' 'a-z' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' | cut -c1-40 | sed -E 's/-+$//')
```

A branch already on origin keeps whatever slug it has; look it up with `git ls-remote --heads origin 'agent/local-spec-<n>-*'` rather than recomputing.

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

`drive-spec land` removes a landed slice's worktree, its local branch, and its remote branch. A repo with "Automatically delete head branches" on has already removed the remote branch at merge, so the delete runs only when it is still there. A cloud session's GitHub proxy rejects branch deletion, so there the remote branch stays until that setting removes it.
