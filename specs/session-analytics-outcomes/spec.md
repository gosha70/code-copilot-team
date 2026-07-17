# Spec: session-analytics outcomes (E9 outcome slice)

Issue #92, follow-up to #91 (link slice, `4f9c9c5`). Base: the shipped
`correlate` pipeline. Grounding (verified 2026-07-17): `score.json`
(`scripts/benchmark_runner/run.py`, schema `benchmarks/schema/score.schema.json`)
carries the stable identity (`benchmark_id, task_id, backend_id, run_id,
attempt`), `result` ∈ {pass, fail, error, timeout}, `scores{tests_passed,
lint_passed, typecheck_passed, required_files_present, timeout}` and
`derived{elapsed_seconds, files_changed, lines_added, lines_removed}`. A NEW
table requires no migration: `apply_ddl` re-runs `CREATE TABLE IF NOT EXISTS`
idempotently on every command, so existing DBs pick it up automatically (the
#91 lesson: new columns can't retrofit, new tables can). Scope = the
**outcomes slice** (2026-07-17 decision): score ingestion + stable identity +
comparison aggregate + caller-owned transactions. No Studio UI, no fuzzy
fallback.

## User Scenarios

- US1: As an operator, running `correlate` also captures each attempt's
  benchmark outcome (pass/fail/error/timeout + verify scores + diff stats)
  into the store, keyed by the stable run identity — so pruning the runs tree
  later doesn't destroy the analytical record.
- US2: As an analyst, I can compare sessions BY benchmark result: the
  dashboard tells me sessions/cost/KPI averages for passing vs failing runs,
  and the export gives me the raw `benchmark_results` table.
- US3: As an operator, a mid-run failure no longer hides what was done — the
  partial summary is printed, and the store isn't littered with per-record
  commits.

## Requirements

- FR-1: **`benchmark_result` table** (`001_core.sql`, `CREATE TABLE IF NOT
  EXISTS`): `id {PK}`, `run_dir` (UNIQUE — the resolve()d attempt dir, same
  value the link stamps), `benchmark_id`, `task_id`, `backend_id`, `run_id`,
  `attempt` (INT), `result` (pass/fail/error/timeout), `tests_passed`,
  `lint_passed`, `typecheck_passed` (BOOLEAN), `elapsed_seconds` (REAL),
  `files_changed`, `lines_added`, `lines_removed` (INT), `session_ref`
  (nullable → `copilot_session.id`), `ingested_at` TEXT. No change to any
  existing table.
- FR-2: **Score ingestion in `correlate`** — for each scanned attempt dir,
  parse the sibling `score.json`: missing → counted `scores_missing`, skipped;
  malformed/unparseable → logged + counted `scores_missing`, never fatal
  (same resilience contract as run-record parsing). Well-formed → upsert
  `benchmark_result` (ON CONFLICT (run_dir) DO UPDATE — idempotent re-runs),
  with `session_ref` resolved via the SAME `(copilot='claude-code',
  session_id)` equi-join used by the link (NULL when unmatched/out-of-scope).
  Out-of-scope backends (foreign `backend_id`): outcome row IS still stored
  (the result table is backend-agnostic — identity includes backend_id), but
  `session_ref` stays NULL and no link is attempted (unchanged #91 scoping).
- FR-3: **Explicit counters extended** — `CorrelationStats` gains
  `scores_ingested` + `scores_missing`; the summary still prints every
  counter via `as_dict()` (nothing hidden).
- FR-4: **Caller-owned transaction** (deferred #91 review item, in scope by
  design): `link_benchmark_run` and the new result upsert stop committing per
  record; `_cmd_correlate` commits ONCE after the scan completes. On a
  mid-run exception: rollback is acceptable for uncommitted work, but the
  partial `CorrelationStats` gathered so far MUST be printed (stderr) before
  returning `EXIT_RUNTIME` — the operator always sees what was processed.
- FR-5: **Comparison aggregate** — `dashboard.benchmark_outcomes(db)`:
  grouped by `result` → `{result, attempts, linked_sessions, total_cost_usd,
  avg_duration_seconds}` (cost/duration only over linked sessions; unlinked
  attempts still counted). Merged into the existing
  `GET /api/dashboard/benchmark` payload under `"by_result"`. No Studio UI.
- FR-6: **Export** — `benchmark_results` added to the E7 export tables
  (columns constant + streamed SELECT + bool normalization, matching the
  existing table pattern); exportable via `--table benchmark_results` and
  included in `--table all`.
- FR-7: **Tests** — unit: score parsing (well-formed / missing / malformed /
  non-dict scores), counter exactness, identity extraction; sqlite
  integration: upsert + idempotent re-run (one row), session_ref resolution
  (linked vs organic), aggregate grouping, export table; FastAPI endpoint
  payload gains `by_result`. Single-commit behavior: a failing record mid-scan
  still prints the partial summary (injected fakes).
- FR-8: **Docs** — README: outcomes section (what's stored, stable identity
  rationale, the by_result aggregate, the single-commit semantics).

## Constraints

- Python stdlib only; no new dependencies; no change to existing tables, to
  `ingest()`, or to redaction (score.json contains no session content —
  redaction-safe by construction).
- All SQL parameterized; column/table names via shared constants.
- One issue per PR: this bundle covers exactly #92 (transaction ownership is
  declared in-scope here, closing the #91 follow-up).
