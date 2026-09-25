---
name: optimise-query
description: Use when a page, endpoint, or service object is slow and you want to systematically find and eliminate the bottleneck through a measure → profile → fix → re-measure loop. Invoke with an optional max iterations argument (default 10).
---

# Optimise Query

Measure first. Fix second. Never guess.

Run up to the requested number of iterations (default: 10). Stop early when the improvement per iteration drops below ~10% or the bottleneck is infrastructure rather than code. Report a results table at the end.

## Step 1 — Establish a baseline

Run the target code **3–5 times** in a single process to separate cold (first-connection) overhead from the true warm steady-state:

```ruby
# Rails — run via: bundle exec rails runner benchmark.rb
require 'benchmark'
start_date = ...
times = 5.times.map { Benchmark.realtime { MyService.call(...) } }
puts "Runs: #{times.map { (_1 * 1000).round(1) }.join(', ')}ms"
puts "Warm avg (runs 2-5): #{(times[1..].sum / 4 * 1000).round(1)}ms"
```

Record **both** the cold run (run 1) and the warm average (runs 2–5). The warm average is the number that matters for a running web server; the cold run is only relevant for background jobs or cron tasks that run infrequently.

## Step 2 — Profile to find the bottleneck

Run **all three probes** before deciding what to fix. Don't fix the first thing you see.

### 2a — Count and time SQL queries

```ruby
ActiveRecord::Base.logger = Logger.new(STDOUT)
MyService.call(...)
ActiveRecord::Base.logger = nil
```

Look for:
- The same query repeated N times (N+1)
- Any single query over ~5 ms
- Subqueries generated from an AR relation passed to `where(association: relation)`

### 2b — Phase-by-phase wall time

Split the service manually to find which phase dominates:

```ruby
t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC, :millisecond)
users = User.where(...).includes(:team).to_a
t1 = Process.clock_gettime(Process::CLOCK_MONOTONIC, :millisecond)
hours = WorkUnit.where(...).group(...).sum(:hours)
t2 = Process.clock_gettime(Process::CLOCK_MONOTONIC, :millisecond)
puts "Load users: #{t1-t0}ms | Aggregate: #{t2-t1}ms"
```

### 2c — EXPLAIN ANALYZE the slow query

For any query over ~3 ms:

```ruby
sql = MyModel.where(...).group(...).to_sql
result = ActiveRecord::Base.connection.execute("EXPLAIN (ANALYZE, BUFFERS) #{sql}")
result.each { |r| puts r['QUERY PLAN'] }
```

Watch for:
- `Seq Scan` with high "Rows Removed by Filter" → missing index
- `IN (SELECT ...)` correlated subquery → materialize the IDs first
- No parallel workers on large aggregation → may need an index to avoid sort

## Step 3 — Pick the highest-impact fix

Choose **one fix per iteration**, highest ROI first:

| Symptom | Fix |
|---------|-----|
| Same query repeated N times (N+1) | Bulk pre-load or single aggregation query |
| `includes(:assoc)` still fires per-row query | Association uses a JOIN scope — bulk-load separately with one query |
| `where(assoc: relation)` generates subquery | Materialise: `.to_a` then `where(id: records.map(&:id))` |
| `Seq Scan` removing most rows | Add composite index on the filter columns |
| Per-object computation in a loop | Pre-compute a lookup hash outside the loop |
| First-query overhead dominates | Infrastructure (connection pool); not fixable in app code — stop here |

## Step 4 — Implement the fix

Apply the single chosen fix. Do not opportunistically clean up other things in the same iteration — it makes the measurement meaningless.

## Step 5 — Verify and re-measure

Run the test suite for the changed file first:

```bash
bundle exec rspec spec/path/to/relevant_spec.rb
```

Then re-run the benchmark (same script as Step 1). Record cold and warm results.

## Step 6 — Loop or stop

Repeat from Step 2 until one of:
- You have reached the requested iteration limit
- The warm improvement this iteration is less than ~10% of the previous result
- Profiling shows the remaining time is infrastructure overhead (DB connection establishment, OS page cache misses) rather than application code — these cannot be fixed without caching or infrastructure changes
- All remaining queries are under ~2 ms each

## Step 7 — Report

Present a summary table:

| Iteration | Change | Cold (ms) | Warm avg (ms) |
|-----------|--------|-----------|---------------|
| Baseline  | —      | X         | X             |
| 1         | What changed | X | X |
| …         | …      | …         | … |

State the overall warm speedup (e.g. "5× faster per request") and the query count reduction (e.g. "39 queries → 4"). Note any remaining bottlenecks that are infrastructure rather than code.

## What NOT to do

- Don't skip Step 2 and guess at the fix — the bottleneck is almost never where you expect
- Don't fix multiple things in one iteration — you won't know which change helped
- Don't treat cold-run time as the production metric for a web app with a connection pool
- Don't add caching as the first resort — eliminate unnecessary work before hiding it
- Don't declare victory after one iteration — run the loop until warm gains flatten out
