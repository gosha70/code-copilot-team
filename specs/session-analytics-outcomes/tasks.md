# Tasks: session-analytics outcomes (E9 outcome slice)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: benchmark_result table + score ingestion

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `benchmark_result` CREATE TABLE IF NOT EXISTS (identity + outcome + nullable session_ref, UNIQUE(run_dir)) + session_ref index (FR-1) | `config_data/ddl/postgres/001_core.sql`, `003_indexes.sql` | build | [ ] |
| 2 | | `iter_run_records` parses sibling `score.json` (missing/malformed → None, counted, never fatal); score payload carried on the record (FR-2) | `scripts/session_analytics/correlate.py` | build | [ ] |
| 3 | | `correlate_links` calls injected `store_result_fn`; `CorrelationStats` + `scores_ingested`/`scores_missing`; out-of-scope backends stored without link (FR-2, FR-3) | `scripts/session_analytics/correlate.py` | build | [ ] |
| 4 | | `upsert_benchmark_result` (parameterized, ON CONFLICT(run_dir) DO UPDATE, session_ref equi-join); `link_benchmark_run` drops per-record commit (FR-2, FR-4) | `scripts/session_analytics/relational/store.py` | build | [ ] |
| 5 | | `_cmd_correlate`: wire store fn; single commit post-scan; partial summary to stderr on failure → EXIT_RUNTIME (FR-4) | `scripts/session_analytics/cli.py` | build | [ ] |
| 6 | [P] | Constants: `TBL_BENCHMARK_RESULT`, `SCORE_FILENAME`, column names | `scripts/session_analytics/constants.py` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] apply_ddl on an EXISTING sqlite file creates benchmark_result (no-migration claim)
- [ ] Re-running correlate → one row per attempt dir, updated not duplicated
- [ ] Mid-scan failure prints partial counters (stderr) and exits EXIT_RUNTIME; success path commits once

---

## US2: comparison aggregate + export

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 7 | | `dashboard.benchmark_outcomes(db)` by result (attempts, linked_sessions, total_cost_usd, avg_duration_seconds); merged as `by_result` into /api/dashboard/benchmark (FR-5) | `api/dashboard.py`, `api/server.py` | build | [ ] |
| 8 | [P] | `benchmark_results` export table (columns constant, streamed SELECT, bool idx, in `--table all`) (FR-6) | `scripts/session_analytics/export.py` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] by_result groups pass/fail correctly; cost only from linked sessions (NULL-safe)
- [ ] `--table benchmark_results` exports; `--table all` includes it; existing tables unchanged

---

## US3: tests + docs

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 9 | | Tests per FR-7 (score-parse unit cases, counters, partial-summary, sqlite upsert/idempotency/session_ref/aggregate/export, FastAPI payload) | `tests/test_correlate.py` (extend) | build | [ ] |
| 10 | [P] | README outcomes section (stored fields, stable-identity rationale, by_result, single-commit semantics) (FR-8) | `scripts/session_analytics/README.md` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] Suite green incl. fastapi run; tests deterministic (no real benchmark run)
- [ ] README documents outcomes + deferred Studio-UI scope

---

## Final Verification

- [ ] Full unittest suite + fastapi/httpx run + `next build` green
- [ ] apply_ddl idempotent on fresh AND pre-existing DBs
- [ ] All SQL parameterized; names via constants; no change to existing tables/ingest/redaction
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
