# Test-pruning campaign

Campaign mode prunes one area's whole test surface in one branch: a namespace (`Billing::`), an engine, or a domain spanning models, controllers, jobs, and system specs. The owner boundaries, junk patterns, retention bar, candidate evidence, and validation in [SKILL.md](SKILL.md) apply to every lane; this file adds the order of work. Each step ends on its completion criterion; start the next only once it holds.

## 1. Baseline

At a pinned `main` SHA, record the area's test and support line counts (`spec/support`, factories, fixtures), SimpleCov line coverage of its production files if available, and every test file's pass/fail state. Keep baseline failures in their own list — they are bug reports until proven stale.

Done when every in-scope test file has a recorded baseline result.

## 2. Lanes

Split the surface into **lanes** along production owner boundaries, not spec directory names — e.g. for billing: plans & pricing, checkout, invoicing, webhooks, dunning jobs, admin UI. Include the area's cases in shared specs, `shared_examples`, and system specs.

Done when every test file and shared example the area owns belongs to exactly one lane.

## 3. Ledger per lane

Give each lane to its own read-only subagent. It reads every assigned test in full (including `let` chains, factory traits, and `shared_examples` bodies) plus the production owners, callers, and history. Each example goes into a written **ledger** with one mark; a table-driven block is one entry unless rows need different marks.

- `R` retain — name the contract and the bug it catches; note a move to a better owner file;
- `F` fix — keep the contract, repair the assertion (a negative that passes for the wrong reason, a setup that skips the path its name claims);
- `C` consolidate — name the keeper that absorbs the assertion first;
- `D` delete — name the remaining proof, or why no contract exists.

Judge a test by its assertions, not its name.

Done when every example in the lane has a mark and an evidence line.

## 4. Layer plan per lane

The ledger is input, not the edit list. A second read-only pass looks for the redundant **layer**: e.g. model, request, and system specs all walking the same pricing branches when one request-spec table would own them. Name the **keeper** suite per contract; prefer the real HTTP boundary with WebMock over a stubbed collaborator. Correct ledger errors this pass finds.

Done when each lane plan names its retired files, keeper per contract, assertions to carry into keepers, and seams unlocked.

## 5. Cutover

Edit lane by lane. Serialise changes to shared `spec/support`, factories, and fixtures through one owner. With each lane, delete the seams it unlocks (injection writers, `Rails.env.test?` branches, reset methods) and factory traits no remaining test uses. Put durable test-ownership rules for the area in its `AGENTS.md` / `CLAUDE.md`, drawn from mistakes this campaign actually found.

Done when every lane plan is applied and each lane's keepers pass.

## 6. Preservation review

Have independent subagents, one per boundary group, compare deleted coverage against the keepers. They look for contracts that lost their only proof, and for new assertions that cannot fail. For each restored contract, make one deliberate **mutation** of the owner, confirm the keeper goes red, then restore the source byte for byte. If `mutant` is configured, run it on the area's owners instead.

Done when every reported gap is restored or rejected with source evidence, and every restored contract has a caught mutation.

## 7. Product defects

A baseline failure that survives into a keeper is a bug. Fix it at its owner in a separate commit, with a **control** run: revert the fix, show the keeper red; reapply, show it green. Record unrelated product discrepancies as follow-ups rather than fixing them in the campaign.

Done when each repaired defect has a red control and a green candidate on the same spec.

## 8. Reconcile and hand off

Merge `main` rather than rebasing a long campaign. When `main` modified a file the campaign deleted, keep the deletion and port the new contract into the keeper; confirm every regression `main` added still has a home. Rerun the whole suite on the merged head.

Hand off with the [SKILL.md](SKILL.md) report, plus:

- baseline and final test/support line counts, production counted separately;
- coverage before and after per production owner;
- lanes, retired layers, and keepers;
- preservation gaps found and their mutations;
- product defects with control and candidate proof.
