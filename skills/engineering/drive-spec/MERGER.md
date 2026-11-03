# Merger brief

`drive-spec build` fills the placeholders and writes this to `<notes>/brief-merge-<m>.md` when `integrate` exits 3 on a slice, for the merger agent it launches in the slice worktree, prompted `Read <file> and follow it.`. A placeholder `build` does not fill fails it.

```markdown
You are resolving one merge conflict between a slice and its spec branch.

Worktree: <path>, on the branch of slice #<m> (`gh api repos/<repo>/issues/<m> --jq '.title, .body'`) of spec #<spec>. Every command runs there. Commits go on the current branch; the orchestrator pushes and integrates, so leave pushing and PRs alone.

Merging the spec branch into the slice conflicted in: <files>. The merge was aborted, so the worktree is clean. Run `<merge>` to start it again, resolve every conflict so the result keeps what both sides meant, and commit the merge with its default message. Read first: `CLAUDE.md` or `AGENTS.md`, and the commits on both sides of each conflicted file. Change nothing beyond the conflicts; a fix the merge needs to pass the gate goes in its own commit, imperative present tense, subject line only.

Then run the verify gate: `<skill dir>/drive-spec verify <spec> <path> --wait-minutes 9`, in the foreground with a 10-minute Bash timeout. Exit 6 prints `running …`: run the same command again until it prints a gate verdict. Its exit code is the gate verdict, so run it bare: no pipe and no command after it. Red: fix, commit, verify again.

Leave no merge in progress and nothing uncommitted: the orchestrator checks that HEAD contains the commit `<merge>` names, then integrates again. A conflict you cannot resolve is not yours to guess: abort the merge with `git merge --abort` and say why in your response.
```
