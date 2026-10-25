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

`drive-spec open` creates the spec worktree and `drive-spec start` a slice's; this is the contract they implement. Both fetch with `--prune` first.

- **Spec**: an existing worktree on the spec branch is reused and fast-forwarded; else the branch on origin is resumed (a local branch already ahead of it is kept, never reset); else it is cut from `origin/<base>` and pushed at once, which is what lets another session, or a later resume, see the spec is underway.
- **Slice**: an existing worktree is reused; else the local branch, else the branch on origin (with or without an open PR); else a fresh branch from the spec worktree's HEAD after `pull --ff-only`. A crashed run's unpushed commits are never reset away.
- A path that already exists is reused when it is on the expected branch, and refused otherwise. A branch checked out in a worktree the run did not create belongs to another session: git refuses to check it out twice, and the command stops naming the path.
- Bootstrap runs per Bootstrap below, whether the worktree is new or reused.

## Bootstrap

Run `bootstrap` from the config in every worktree `open` or `start` touches, from that worktree's directory, until one succeeds: a marker in the worktree's own git dir, holding the command's hash, records the success, so a failed or changed bootstrap runs again on the next call. Output goes to `logs/bootstrap-<worktree>.log`; a non-zero exit prints its tail and fails the command before any agent starts. Absent config means no bootstrap step.

## Remove

`drive-spec land` removes a landed slice's worktree, its local branch, and its remote branch. A repo with "Automatically delete head branches" on has already removed the remote branch at merge, so the delete runs only when it is still there. A cloud session's GitHub proxy rejects branch deletion, so there the remote branch stays until that setting removes it.
