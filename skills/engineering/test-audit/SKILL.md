---
name: test-audit
description: "Invoke whenever writing, changing, reviewing, or sweeping tests in a Rails app. Authoring gate for new specs plus audit workflow for low-value, implementation-coupled, or duplicative tests and the test-only production seams they demand."
---

# Test Audit

Three modes, one value bar:

- **Authoring** — gate every new or changed test at write time.
- **Audit** — a focused sweep for **junk**: tests that re-assert source, duplicate stronger proof, couple to implementation, or keep test-only **seams** alive in production code. Land one coherent batch; optimise for confidence, not deletion count.
- **Campaign** — prune one whole area's test surface (a namespace, engine, or domain such as `billing`). Before starting one, read [CAMPAIGN.md](CAMPAIGN.md).

Read `AGENTS.md` / `CLAUDE.md`, `.rspec` or `test/test_helper.rb`, `spec/support/`, and `Gemfile` test group first: they tell you the framework (RSpec or Minitest), factories vs fixtures, and whether `shoulda-matchers`, `webmock`/`vcr`, `simplecov`, or `mutant` are available.

## Owner boundaries

Each contract has one primary **owner** test at the strongest boundary that can observe it:

| Contract | Owner |
|---|---|
| Domain rule, calculation, state transition | model / service / PORO spec |
| HTTP status, params, auth, JSON shape, redirects | request spec (`spec/requests`, `test/integration`) |
| User flow across pages, JS behaviour | system spec |
| Enqueue, retry, idempotency | job spec + one enqueue assertion at the caller |
| Email recipients, subject, key content | mailer spec |
| Who may do what | policy spec (Pundit/ActionPolicy) |
| External API contract | spec against a `webmock`/`vcr` stub of the real wire format |

Another layer earns a test only for a distinct risk the owner cannot reach (a transaction boundary, a Turbo/JS interaction, a callback firing on the real request path). Legacy controller specs (`assigns`, `render_template`) are superseded by request specs.

## Authoring gate

Before adding a test, answer four questions; a missing answer means do not add it yet:

1. What observable behaviour, invariant, or independent contract does it protect?
2. What credible regression makes it fail?
3. Why does existing coverage not already catch it? Prefer adding a row to an existing table/`shared_examples` or reusing a factory trait over a near-duplicate example; consolidate duplicated setup in the same change.
4. Does it need a production seam no production caller needs? If yes, move the test to the owner boundary instead.

Then check it against every [junk pattern](#junk-patterns); a match fails the gate unless the [retention bar](#retention-bar) names the contract it independently guards. A test that goes red under a behaviour-preserving refactor asserts implementation; rewrite it at the owner before landing.

A bug regression test must go red on the pre-fix code for the intended reason and green after the fix at the owner. One regression at the owner covers the bug; replay it at another layer only for a distinct risk.

## Junk patterns

Shared checklist: the gate rejects new tests that match; audits hunt existing ones.

- assertion-free examples, or examples asserting only `have_http_status(:ok)` / `be_present` / `be_valid` on a record built to be valid;
- restating declarations: `have_many`, `belong_to`, `validate_presence_of`, `delegate`, enum value lists, `routes.rb` routing specs — unless the declaration is itself the contract (see retention bar);
- tests of Rails or gem behaviour (`has_secure_password` hashes, `dependent: :destroy` deletes, `scope` returns a relation);
- private methods reached via `send` / `instance_variable_get`, duplicated at a public boundary;
- `expect(subject).to receive(...)` or `have_received` on the object under test — call-shape, not outcome;
- mocks that implement the asserted behaviour: stubbed AR chains (`allow(User).to receive_message_chain(:active, :where)`), `allow_any_instance_of`, stubbed service returning the value then asserted;
- expected values produced by the code under test (calling the presenter/serializer to build the expectation) or copied verbatim from it (full JSON dumps, `to_sql` strings, i18n text);
- duplicate proof of one contract across model, request, and system specs;
- fixtures/factories that supply the state the owner should produce (setting `status: :paid` instead of running the payment path), or persistence asserted on a column the path never writes;
- negative cases that pass for an unrelated reason: a 404 from a missing record instead of the authorization guard under test, a validation failing on a different attribute;
- names or contexts that promise more than the setup exercises (`"when the subscription has expired"` with no expiry in the setup);
- tests whose only purpose is preserving a seam: `attr_writer`/`attr_accessor` for injection, `if Rails.env.test?` branches, `reset!` class methods, methods made public for the spec;
- dead production code whose only callers are specs.

## Retention bar

Keep a test when it independently enforces a public API/JSON contract, authorization, security (strong params, CSRF, tenant scoping), migration or data-migration, DB constraint, money/timezone/rounding, webhook or external-API wire format, job idempotency, config default, or a user-facing copy/key another system consumes. Also keep:

- call ordering or `receive` expectations when the call is the observable effect (an outbound HTTP request, an enqueued job, an emitted event);
- a declaration matcher when the declaration is the contract (a uniqueness validation backed by a unique index; a `dependent:` rule that prevents orphaned billing data);
- regressions with a credible failure mode;
- a retained test red on the baseline: treat it as a possible product bug, reproduce it, and fix the owner rather than deleting it.

Slow or brittle is not a deletion reason. A test that resembles implementation may still be the only proof of a contract; prove otherwise before removing it.

## Audit workflow

### 1. Discovery

Read-only; report evidence before editing. For broad scope, dispatch parallel read-only subagents, one per lane:

- `app/models`, `app/services`, POROs, `lib/`;
- controllers, request/integration specs, policies, serializers;
- jobs, mailers, channels, external clients;
- system specs;
- a cross-cutting grep sweep for the junk patterns (`send(:`, `receive_message_chain`, `allow_any_instance_of`, `Rails.env.test?`, `have_http_status(:ok)$`, `it { is_expected.to`).

Outside campaign mode, prefer a few high-confidence candidates over a large speculative inventory.

### 2. Candidate evidence

Before judging a candidate, read the whole test, its production owner, entry point, callers, overlapping tests, and `git log -p` for why it exists. Record every field below; a missing field means the candidate is not ready:

- test name and `path:line`;
- the failure it can actually detect;
- non-test callers of the covered code or seam (`grep -rn` outside `spec/`/`test/`);
- the remaining owner proof, or why no contract exists;
- production code or seam the deletion unlocks;
- risk, and the focused command that validates it.

When coverage is ambiguous, make one deliberate **mutation** of the owner (flip a condition, drop a line), run the remaining owner tests, confirm they go red, then restore the source byte for byte. A mutation no keeper catches means the candidate stays.

### 3. Edit

Pick one coherent owner-boundary batch. Delete obsolete seams and dead production paths outright. Move retained regressions to their owner file. Collapse repeated cases into one table or `shared_examples`. Prefer net-negative production LOC; convert only candidates with complete evidence.

### 4. Validation

1. Run the touched files and their siblings: `bundle exec rspec <paths>` or `bin/rails test <paths>`.
2. Run the mutations recorded for deleted candidates once more against the final keepers.
3. `bundle exec rubocop <changed files>` if configured, then `git diff --check`.
4. If SimpleCov is present, compare line coverage of each touched production owner before and after; any drop needs a named reason.
5. Run the full suite (or the project's CI command from `bin/ci` / `.github/workflows`).
6. `git diff --numstat`: report production separately from tests and support.

Done when every step is green and each deleted test's contract has a named keeper or a stated "no contract".

### 5. Landing

Commit only when the user asks; use the `git-commit` skill. After landing, rerun discovery on current `main` for the next batch.

## Handoff

Report:

- junk categories removed, with counts;
- production simplifications and seams deleted;
- false positives retained and why;
- mutations run and their outcome;
- commands actually run and results;
- production vs test LOC;
- named follow-ups (including suspected product bugs).
