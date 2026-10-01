---
name: review-fix-pr
description: "Review an open PR, post the review, then fix every finding and reply on the PR."
disable-model-invocation: true
---

# review-fix-pr

`/review-fix-pr [<pr>] [--review-only]`

The local run of the `agent:review-pr` → `agent:implement` label pair: one pass reviews the PR and posts the review, a second fixes the findings, pushes, and replies thread by thread. `<pr>` defaults to the PR whose head is the current branch.

The PR head is worked in its own worktree; the checkout you are standing in is never touched. Reviewer and fixer are separate subagents so the fixer never grades its own review. Communicate with them through context pointers — PR number, review id, worktree path, verify gate — and let them read the rest themselves.

Briefs, filled in and handed to the subagents:

- [`REVIEWER.md`](REVIEWER.md) — the read-only review pass.
- [`FIXER.md`](FIXER.md) — the fix pass.

## Steps

1. **Resolve the run.** `gh pr view <pr> --json number,title,state,baseRefName,headRefName,isCrossRepository,closingIssuesReferences`. Refuse a closed PR or a fork head (no push access). Read `bootstrap`, `verify`, and `worktreeRoot` from `.claude/drive-spec.json` in the repo root when present; else no bootstrap, verify gate from the repo's `CLAUDE.md` or `AGENTS.md`, root `<repo>/.claude/worktrees`. Done when PR, base, head, linked issue, verify gate, and worktree path are printed.

2. **Open the PR worktree.** `git fetch --prune origin`, then `git worktree add <root>/pr-<n> -B <head> origin/<head>`. Reuse the path when it is already on `<head>`; a head checked out elsewhere belongs to another session — stop and name the path. Run bootstrap there. Done when the worktree sits at origin's head.

3. **Review.** Dispatch a reviewer subagent with REVIEWER.md filled in. It writes a reviews-API payload to `<root>/pr-<n>.review.json`. Post it: `gh api --method POST repos/{owner}/{repo}/pulls/<n>/reviews --input <file>`; if the API rejects an inline line, post the summary alone with `-f event=COMMENT -f body=…`. Record the returned review id. Done when the review is on the PR. With `--review-only`, skip to step 6.

4. **Fix.** Dispatch a fixer subagent with FIXER.md filled in. Done when it reports green with commits and one reply per addressed comment id. Red halts the run: print its reason and the worktree path, leave the worktree, push nothing.

5. **Push and reply.** Confirm `git -C <worktree> log origin/<head>..HEAD` is non-empty, then push. Post each reply as a thread reply: `gh api --method POST repos/{owner}/{repo}/pulls/<n>/comments/<id>/replies -f body=…`; a since-deleted comment is skipped, never fatal. Post the fixer's summary with `gh pr comment <n>`. Done when every reply and the summary are on the PR.

6. **Clean up.** `git worktree remove --force <root>/pr-<n>`, `git worktree prune`, print the PR URL and a count of findings raised, fixed, and declined.
