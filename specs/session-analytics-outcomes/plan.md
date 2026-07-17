---
spec_mode: full
feature_id: session-analytics-outcomes
risk_category: integration
justification: |
  Ingests benchmark score.json outcomes into a NEW benchmark_result table
  (CREATE TABLE IF NOT EXISTS — no migration; existing DBs pick it up via the
  idempotent apply_ddl) and adds a by-result comparison aggregate. Extends the
  shipped correlate pipeline; folds in the #91-review transaction-ownership
  fix (caller-owned single commit + failure-time partial summary). Stdlib
  only, parameterized SQL, no change to existing tables/ingest/redaction.
status: approved
date: 2026-07-17
issue: 92
origin:
  issue: gosha70/code-copilot-team#92
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/92
  origin_claim: |
    Issue #92 (E9 outcomes slice): a new benchmark_result table (stable
    identity benchmark_id/task_id/backend_id/run_id/attempt + result/scores/
    diff stats, UNIQUE(run_dir), nullable session_ref) populated by correlate
    from each attempt dir's score.json (missing/malformed counted, never
    fatal; out-of-scope backends stored without session_ref); explicit
    counters extended (scores_ingested/scores_missing); caller-owned single
    commit with a failure-time partial summary (closing the #91 follow-up);
    a by-result dashboard aggregate on GET /api/dashboard/benchmark; the
    benchmark_results export table. No Studio UI, no fuzzy fallback.
---

# Plan: session-analytics outcomes (E9 outcome slice)

Grounded (verified 2026-07-17): score.json fields + result enum
(run.py `_classify_result`: timeout > error > pass/fail); apply_ddl re-runs
CREATE TABLE IF NOT EXISTS on every command (new tables need no migration);
the correlate pipeline (iter_run_records / correlate_links / link_benchmark_run
/ _cmd_correlate) shipped in 4f9c9c5 is the extension surface.

## Deliverables

1. **DDL** (`001_core.sql`): `benchmark_result` table per FR-1 (+ an index on
   `session_ref` in `003_indexes.sql`).
2. **`correlate.py`**: `RunRecord` gains the parsed score payload (or a
   sibling `ScoreRecord`); `iter_run_records` reads `score.json` next to each
   run-record (missing/malformed → None + counter); `correlate_links` calls an
   injected `store_result_fn(record) -> None` alongside `link_fn`, extends
   `CorrelationStats` with `scores_ingested`/`scores_missing`.
3. **`relational/store.py`**: `upsert_benchmark_result(db, ...) -> None`
   (parameterized, ON CONFLICT(run_dir) DO UPDATE) resolving `session_ref` via
   the session equi-join; `link_benchmark_run` loses its per-record
   `db.commit()`.
4. **`cli.py` `_cmd_correlate`**: wires the real store fn; ONE `db.commit()`
   after the scan; on exception prints the partial summary to stderr before
   `EXIT_RUNTIME`.
5. **Dashboard**: `benchmark_outcomes(db)` grouped by result; merged into the
   `/api/dashboard/benchmark` payload as `by_result`.
6. **Export**: `benchmark_results` table (constants + columns + streamed
   SELECT + bool indexes).
7. **Constants**: table/column names + `SCORE_FILENAME = "score.json"`.
8. **Tests** (`test_correlate.py` extension or `test_outcomes.py`) per FR-7;
   **README** per FR-8.

## Design decisions to confirm at approval

- **D-store-outcomes-for-foreign-backends** — benchmark_result stores ALL
  backends' outcomes (identity includes backend_id); only session linking
  stays claude-code-scoped. *(Recommend — the result table is analytical
  record, not linkage; aider/codex outcomes are useful the day those backends
  ship, and it costs nothing now.)*
- **D-upsert-key** — `UNIQUE(run_dir)` (the resolve()d attempt dir), with the
  stable identity stored as data. A `UNIQUE(benchmark_id, run_id, task_id,
  attempt, backend_id)` natural key is stricter but breaks if a runs tree is
  copied; run_dir matches the link key exactly. *(Recommend run_dir.)*
- **D-partial-summary-format** — on failure, the partial summary prints as the
  same JSON shape to stderr (stdout stays reserved for the success summary).
  *(Recommend.)*
- **D-aggregate-cost-source** — `total_cost_usd` per result comes from summing
  `copilot_turn.cost_usd` of LINKED sessions only (same NULL-safe semantics as
  the E5 KPIs); unlinked attempts appear in `attempts` but contribute no cost.
  *(Recommend.)*
- **D-parse-strictness** (user guardrail, 2026-07-17): tolerant of MISSING /
  partial fields (absent scores/derived keys → NULL columns, row still
  stored), but STRICT about malformed types where they would corrupt
  aggregates — `result` not in {pass,fail,error,timeout}, non-numeric
  elapsed/lines counters, non-bool verify flags → the row is counted
  `scores_missing` and skipped, never coerced. Missing ≠ malformed.

## Out of scope

- Studio comparison UI (later slice); fuzzy fallback; E6 push; E10.
- Any change to existing tables, `ingest()`, redaction, or the judge.

## Test strategy

Unit (stdlib, injected fakes — no FS/DB): score-parse cases (well-formed,
missing file, malformed JSON, non-dict scores/derived), counter exactness
including the new two, partial-summary-on-failure via a store_result_fn that
raises. sqlite integration: apply_ddl creates the table on an EXISTING db
file (the no-migration claim), upsert idempotency (re-run → one row,
updated), session_ref linked vs NULL, by_result aggregate with a seeded
pass+fail pair, export table streams. FastAPI: /api/dashboard/benchmark
payload gains by_result (with fastapi/httpx installed). Studio: next build
stays green (no studio change).
