# Spec: session-analytics correlate (E9 benchmark ↔ session linking)

Issue #91 (E9, final Tier-2 candidate from the #65 prioritization). Base: the
#63 pipeline + E5/E8/E7/E6. Groundwork (verified 2026-07-16): the
`copilot_session` table already ships a `benchmark_run_dir VARCHAR(1000)`
column (`config_data/ddl/postgres/001_core.sql`) that nothing writes or reads;
the Claude Code `session_id` is captured on BOTH sides — benchmark
`run-record.json → backend.metadata.session_id` (`scripts/benchmark_runner/run.py`)
and `copilot_session.session_id` — giving an exact equi-join. No schema change
is required; E9 is write-logic + surfacing only. Scope = the **link + export +
summary slice** (2026-07-16 decision): `session_id` exact-join only, no
outcome ingestion, no Studio UI, no fuzzy fallback.

## User Scenarios

- US1: As an operator, after a benchmark run I run `session-analytics
  correlate --runs-root <dir>` and it stamps each analytics session that came
  from a benchmark attempt with that attempt's artifact directory, reporting
  how many it linked and how many runs had no session to match.
- US2: As an analyst, an exported session row carries its `benchmark_run_dir`,
  and the dashboard tells me how many sessions are benchmark-linked vs organic.

## Requirements

- FR-1: **`correlate` CLI** — `session-analytics correlate --runs-root <dir>
  [--dsn <dsn>]`. Recursively scan `--runs-root` for `run-record.json` files;
  for each record carrying a non-null `backend.metadata.session_id`, set
  `copilot_session.benchmark_run_dir` = the record's containing attempt
  directory on the matching `(copilot='claude-code', session_id)` row
  (idempotent UPDATE — re-running is a no-op when already linked). Exit
  `EXIT_OK`; `--runs-root` that does not exist → `EXIT_USAGE`.
- FR-2: **Testable core** — a pure `correlate_links(records, link_fn)` (or
  equivalent) that takes already-parsed `(session_id, run_dir)` records and an
  injected `link_fn(session_id, run_dir) -> bool` (True = a row was updated),
  returning a `CorrelationStats(scanned, with_session_id, linked, unmatched,
  null_session_id)`. Filesystem walk + JSON parse (`iter_run_records`) is a
  separate, thin IO layer; the CLI wires the real DB `link_fn`, tests inject
  fakes. No real runs-tree walk or DB in the core unit tests.
- FR-3: **Exact-join only** — matching is a strict equi-join on `session_id`.
  A record with a null/absent `session_id` is counted (`null_session_id`) and
  skipped; a record whose `session_id` matches no session row is counted
  (`unmatched`) and skipped. No project_path/time-window fallback.
- FR-4: **Store helper** — `link_benchmark_run(db, copilot, session_id,
  run_dir) -> bool` issues the parameterized UPDATE and returns whether a row
  was affected. `benchmark_run_dir` column name is a shared constant.
- FR-5: **Export** — `benchmark_run_dir` is added to the sessions export
  contract (`export.py` `SESSIONS_COLUMNS` + the session SELECT), so an
  exported session self-documents its benchmark linkage (NULL when organic).
- FR-6: **Summary aggregate** — a pure `dashboard.py` function
  (`benchmark_correlation(db)`) returns `{sessions_total, sessions_linked,
  sessions_unlinked, distinct_benchmark_runs}` over `copilot_session`, included
  in the assembled dashboard payload (backend only — no new Studio UI).
- FR-7: **Tests** — core: exact cycle counts for linked / unmatched /
  null_session_id from injected records; `iter_run_records` parses a
  fixture tree and skips malformed/absent-session records. sqlite integration:
  `link_benchmark_run` sets the column; the export includes it; the dashboard
  aggregate counts linked vs unlinked correctly. No real benchmark run needed.
- FR-8: **Docs** — a README `correlate` section (command, the session_id
  exact-join semantics, the null-session-id/unmatched reporting, and the
  deferred outcome-ingestion / Studio-UI / fuzzy-fallback scope).

## Constraints

- Python stdlib only (`os`/`pathlib`, `json`); no new dependencies; no schema
  change (`benchmark_run_dir` already exists in the shipped DDL).
- Read-only against `benchmarks/`/`benchmark_runner` artifacts — `correlate`
  only READS `run-record.json`; it never writes into the runs tree.
- The UPDATE is parameterized (no SQL string interpolation) and idempotent.
- `benchmark_run_dir` and the `run-record.json` field path are named constants
  (crossing store/export/dashboard/correlate module boundaries).
- Redaction-safe: `correlate` reads only the benchmark run metadata
  (`session_id`, a directory path) and the already-stored session key — it
  never touches raw transcripts or session content.
- One issue per PR: this bundle covers exactly #91.
