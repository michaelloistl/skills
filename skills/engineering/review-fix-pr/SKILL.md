---
name: review-fix-pr
description: "Review an open PR, post the review, then fix every finding and reply on the PR."
disable-model-invocation: true
---

# review-fix-pr

`/review-fix-pr [<pr>] [--review-only]`

Two passes over one PR: one reviews the PR and posts the review, a second fixes the findings, pushes, and replies thread by thread. `<pr>` defaults to the PR whose head is the current branch.

The PR head is worked in its own worktree; the checkout you are standing in is never touched — unless it already *is* the PR head (step 2). Reviewer and fixer are separate subagents so the fixer never grades its own review. Communicate with them through context pointers — PR number, review id, worktree path, verify gate — and let them read the rest themselves.

Briefs, filled in and handed to the subagents:

- [`REVIEWER.md`](REVIEWER.md) — the read-only review pass.
- [`FIXER.md`](FIXER.md) — the fix pass.

GitHub goes through the REST API with `gh api`, never `gh pr` or `gh issue`: those use GraphQL, which the cloud-session GitHub proxy rejects. Resolve the repository once, at run start, from the origin URL (a cloud session's origin points at a proxy `gh` does not recognise, so `{owner}/{repo}` placeholders fail), and fill it into each brief as `<owner/name>`:

```sh
repo=$(git remote get-url origin | sed -E 's#(\.git)?/*$##' | awk -F'[/:]' '{print $(NF-1)"/"$NF}')
```

## Steps

1. **Resolve the run.** Without `<pr>`, take the open PR whose head is the current branch: `gh api "repos/$repo/pulls?state=open&head=${repo%/*}:<branch>" --jq '.[0].number'`. Then `gh api "repos/$repo/pulls/<pr>" --jq '{number, title, state, body, base: .base.ref, head: .head.ref, fork: (.head.repo.full_name != .base.repo.full_name)}'`. The linked issue is the first `#<m>` after a closing keyword (`Closes`, `Fixes`, `Resolves`, any tense) in the body. Refuse a closed PR or a fork head (no push access). Read `bootstrap`, `verify`, and `worktreeRoot` from `.claude/drive-spec.json` in the repo root when present; else no bootstrap, verify gate from the repo's `CLAUDE.md` or `AGENTS.md`, root `<repo root>/.claude/worktrees`. Done when PR, base, head, linked issue, verify gate, and worktree path are printed.

2. **Open the PR worktree.** `git fetch --prune origin`, then `git worktree add <root>/pr-<n> -B <head> origin/<head>`. Reuse the path when it is already on `<head>`. When `<head>` is checked out in the worktree you are standing in — the usual case after opening the PR from it — and that tree is clean and level with `origin/<head>`, work there instead and skip the worktree removal in step 6; dirty or diverged, stop and say so. A head checked out at any other path belongs to another session — stop and name the path. Run bootstrap there. Done when the worktree sits at origin's head.

3. **Review.** Dispatch a reviewer subagent with REVIEWER.md filled in. It writes a reviews-API payload to `/tmp/pr-<n>.review.json` — outside every repo and worktree, because a worktree-isolated session cannot write beside its worktree. Post it: `gh api --method POST repos/$repo/pulls/<n>/reviews --input <file>`; if the API rejects an inline line, post the summary alone with `-f event=COMMENT -f body=…`. Record the returned review id. Done when the review is on the PR. With `--review-only`, skip to step 6.

4. **Fix.** Dispatch a fixer subagent with FIXER.md filled in. Done when it reports green with commits and one reply per addressed comment id. Red halts the run: print its reason and the worktree path, leave the worktree, push nothing, and post the status comment.

5. **Push and reply.** Confirm `git -C <worktree> log origin/<head>..HEAD` is non-empty, then push. Post each reply as a thread reply: `gh api --method POST repos/$repo/pulls/<n>/comments/<id>/replies -f body=…`; a since-deleted comment is skipped, never fatal. Post the fixer's summary: `gh api repos/$repo/issues/<n>/comments -f body=…`. Done when every reply and the summary are on the PR.

6. **Clean up.** Delete `/tmp/pr-<n>.review.json`. If step 2 created the worktree, `git worktree remove --force <root>/pr-<n>` and `git worktree prune`; a reused worktree stays. Print the PR URL and a count of findings raised, fixed, and declined. Post the status comment last. Done when it is on the PR.

## Status comment

A fresh comment on the PR as the run's last action, never an edit: edits notify no one, and this comment is how the operator learns the run is over.

```sh
gh api repos/$repo/issues/<n>/comments -f body=… --silent
```

| Outcome | Body |
|---|---|
| done | `review-fix-pr done: <raised> findings, <fixed> fixed, <declined> declined.` |
| review only | `review-fix-pr done (review only): <raised> findings posted.` |
| halted | `review-fix-pr halted in the fix pass: <one line why>. Worktree kept at <path>.` |
