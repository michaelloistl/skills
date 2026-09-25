---
name: git-commit
description: Commit staged changes (or help stage them first). Shows a summary and waits for confirmation before committing. Use when the user wants to commit, or as the final step of another skill that produces a commit.
---

# Git Commit

## Steps

1. Run `git status` to see what's staged, unstaged, and untracked
2. Run `git diff --staged` to see exactly what will be committed
3. If nothing is staged, show the unstaged changes and ask what to stage
4. If there are untracked files or directories, always list them and ask whether any should be included — do this even when there are already staged or unstaged changes
5. Run `git log --oneline -5` to see recent commit style for reference
6. Write a commit message following the rules below
7. **Show the proposed message and the files to be committed, then wait for explicit confirmation before committing**
8. Only commit after explicit approval
9. After a successful commit, run `git push` and report the result

## Reference argument

If a reference is supplied as an argument (e.g. `/git-commit #42` or `/git-commit gh-42`), append it to the commit message title after a space, e.g. `Fix forecast_days using stale data source #42`. Do not add a reference unless one was explicitly provided.

## Commit message rules

- Single line only: imperative present tense, concise summary
- Keep under 72 characters (including any reference suffix)
- No body, no bullet points, no description — title only
- No Co-Authored-By lines — ever
- No mention of Claude, AI, or any assistant
- No emoji
- No conventional commit prefixes (feat:, fix:, chore:)
- Write as if the developer wrote it — direct, technical, no filler

## What NOT to do

- Don't commit without showing the summary and getting confirmation first
- Don't create empty commits
- Don't amend previous commits unless explicitly asked
- Don't add unrelated files to the commit
- Don't use `git add -A` or `git add .` — stage specific files
