---
spec_mode: full
feature_id: session-analytics-correlate
risk_category: integration
justification: |
  Links benchmark run artifacts to analytics sessions via the existing Claude
  Code session_id. Low risk — no schema change (benchmark_run_dir already
  ships in 001_core.sql), stdlib only, read-only against the benchmark runs
  tree, a single idempotent parameterized UPDATE, and a pure injectable core
  for deterministic tests (no real FS walk / DB). Adds one export column + one
  backend dashboard aggregate; no Studio UI. Tracking #65; builds on
  E5/E8/E7/E6.
status: approved
date: 2026-07-16
issue: 91
origin:
  issue: gosha70/code-copilot-team#91
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/91
  origin_claim: |
    Issue #91 (E9 link + export + summary slice): a `session-analytics
    correlate --runs-root <dir>` command that scans benchmark run-record.json
    files and sets copilot_session.benchmark_run_dir on the matching
    (copilot='claude-code', session_id) row via a session_id EXACT-join only
    (null-session-id / unmatched runs reported, not fuzzy-matched); a testable
    correlate core with an injected link_fn; benchmark_run_dir added to the
    sessions export; a backend dashboard aggregate of linked vs unlinked
    sessions. No schema change (column already ships), no benchmark-outcome
    ingestion, no Studio UI, no project_path/time-window fallback (deferred).
---

# Plan: session-analytics correlate (E9 link + export + summary slice)

Grounded (verified 2026-07-16): `copilot_session.benchmark_run_dir` already
exists in `001_core.sql` (inert); `run-record.json → backend.metadata.session_id`
(`benchmark_runner/run.py`) and `copilot_session.session_id`
(`adapters/claude_code.py`) are the same Claude Code UUID → exact equi-join;
`apply_ddl` is CREATE-only (no ALTER needed since the column already ships);
`store.py upsert_session` omits the column; `export.py SESSIONS_COLUMNS` and
`dashboard.py` are the surfacing points.

## Deliverables

1. **`correlate` core** (`scripts/session_analytics/correlate.py` new):
   `iter_run_records(runs_root)` (thin IO: walk for `run-record.json`, parse,
   yield `(session_id, attempt_dir)`), and a pure
   `correlate_links(records, link_fn) -> CorrelationStats` (scanned /
   with_session_id / linked / unmatched / null_session_id). No DB/FS in the
   pure core.
2. **`correlate` CLI** (`cli.py`): new subcommand `--runs-root` (required) /
   `--dsn`; validates runs-root exists (`EXIT_USAGE`), wires the real
   `link_benchmark_run` as `link_fn`, prints the `CorrelationStats` summary.
3. **Store helper** (`relational/store.py`): `link_benchmark_run(db, copilot,
   session_id, run_dir) -> bool` — parameterized idempotent UPDATE, returns
   rowcount > 0.
4. **Export** (`export.py`): add `benchmark_run_dir` to `SESSIONS_COLUMNS` +
   the session SELECT (NULL for organic sessions).
5. **Dashboard** (`api/dashboard.py`): `benchmark_correlation(db)` aggregate
   included in the assembled dashboard payload.
6. **Constants** (`constants.py`): `COL_BENCHMARK_RUN_DIR` + the
   `run-record.json` field path / filename constants.
7. **Tests** (`tests/test_correlate.py`) per FR-7; **docs** (README) per FR-8.

## Design decisions to confirm at approval

- **D-run-dir-granularity** — store the per-ATTEMPT directory (the folder that
  contains `run-record.json`/`score.json`/`transcript.json`), not the
  top-level run dir. *(Recommend — session_id ↔ attempt is 1:1, so the attempt
  dir is the precise artifact set for that session.)*
- **D-collision** — if two run-records carry the same `session_id` (should not
  happen — each attempt spawns a fresh session), last-writer-wins with a logged
  warning. *(Recommend.)*
- **D-summary-wiring** — include `benchmark_correlation` in the existing
  dashboard payload (backend only); the Studio may ignore it. *(Recommend — the
  natural home for a "comparison view" without new UI.)*
- **D-copilot-scope** — link only `copilot='claude-code'` rows (the only
  backend that emits a session_id). *(Recommend.)*

## Out of scope

- Benchmark **outcome** ingestion (score.json pass/fail into the store); a
  Studio comparison page; the project_path + time-window fuzzy fallback for
  null-session_id runs (all a later E9 issue).
- Any schema/migration change, redaction change, or change to `ingest()`.

## Test strategy

Unittest (stdlib): pure `correlate_links` with injected `(session_id, run_dir)`
records + a fake `link_fn` (returns True/False by a preset matched-set) —
assert exact `scanned/with_session_id/linked/unmatched/null_session_id`.
`iter_run_records` over a small fixture tree (a well-formed record, a
null-session record, a malformed JSON) → yields only the valid session records.
sqlite integration: seed two sessions, `link_benchmark_run` one → assert the
column set + idempotent re-link; export includes `benchmark_run_dir`; the
dashboard aggregate returns linked=1/unlinked=1. No real benchmark run, FS
walk of a live tree, or Postgres in the unit tests.
