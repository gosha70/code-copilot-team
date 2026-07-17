# Tasks: session-analytics correlate (E9 link + export + summary slice)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: correlate core + CLI + store link

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `iter_run_records(runs_root)` (walk for `run-record.json`, parse, yield `(session_id, attempt_dir)`) + pure `correlate_links(records, link_fn) -> CorrelationStats` (scanned / with_session_id / linked / unmatched / null_session_id) (FR-2, FR-3) | `scripts/session_analytics/correlate.py` (new) | build | [ ] |
| 2 | | `link_benchmark_run(db, copilot, session_id, run_dir) -> bool` — parameterized idempotent UPDATE (FR-4) | `scripts/session_analytics/relational/store.py` | build | [ ] |
| 3 | | `correlate` CLI subcommand: `--runs-root` (required, must exist → else `EXIT_USAGE`) / `--dsn`; wires real `link_benchmark_run`; prints the `CorrelationStats` summary (FR-1) | `scripts/session_analytics/cli.py` | build | [ ] |
| 4 | [P] | `COL_BENCHMARK_RUN_DIR` + `run-record.json` filename/field-path constants | `scripts/session_analytics/constants.py` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] `correlate_links` returns exact linked / unmatched / null_session_id counts from injected records
- [ ] `link_benchmark_run` sets the column and is idempotent; UPDATE is parameterized (no string interpolation)
- [ ] Missing `--runs-root` dir → `EXIT_USAGE`; a good run → `EXIT_OK` + summary

---

## US2: Export + summary aggregate

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | | Add `benchmark_run_dir` to `SESSIONS_COLUMNS` + the session SELECT (NULL for organic) (FR-5) | `scripts/session_analytics/export.py` | build | [ ] |
| 6 | [P] | `benchmark_correlation(db)` aggregate (sessions_total / linked / unlinked / distinct_benchmark_runs) included in the dashboard payload (FR-6) | `scripts/session_analytics/api/dashboard.py` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] Export row carries `benchmark_run_dir` (linked = path, organic = empty/NULL)
- [ ] Dashboard aggregate returns correct linked vs unlinked counts; existing dashboard fields unchanged

---

## US3: Tests + docs

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 7 | | Tests: pure core counts from injected records; `iter_run_records` skips null-session/malformed; sqlite integration for link + idempotency + export column + dashboard aggregate (FR-7) | `scripts/session_analytics/tests/test_correlate.py` (new) | build | [ ] |
| 8 | [P] | README `correlate` section (command, session_id exact-join, null/unmatched reporting, deferred outcome/UI/fallback scope) (FR-8) | `scripts/session_analytics/README.md` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] Suite green; correlate core tests deterministic (no real FS walk / DB / benchmark run)
- [ ] README documents the exact-join semantics + the deferred scope

---

## Final Verification

- [ ] Unittest suite passes; `correlate_links` tests are deterministic (injected fakes)
- [ ] `next build` green (no Studio change expected, but the studio CI job stays green)
- [ ] No schema/migration/redaction change; UPDATE parameterized + idempotent
- [ ] `benchmark_run_dir` name is a shared constant across store/export/dashboard/correlate
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
