# Tasks: expectations and their evaluation (A5)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 0 | Owner approves the plan (D1–D11 as corrected 2026-09-25) | `plan.md` | [ ] |
| 1 | Four tables + schema 11 **tables-only, no `_REQUIRED_COLUMNS`**: `expectation_run` (with `run_fingerprint`), `expectation`, `expectation_result`, `expectation_session` keyed by the discovered identity with a nullable `session_ref`; constants for states, statement sources, verifier kinds and bounds (FR-1, FR-3, FR-5, FR-9, FR-11) | `config_data/ddl/postgres/011_expectation.sql`, `relational/db.py`, `constants.py` | [x] |
| 2 | `expectations.py`: `read_ledger()`, `run_fingerprint()` over the `init` event + base + contract digest, `recover_statements()` accepting only hash-matching text, `normalize_state()` (waived before green), `roll_up()`, `evaluated_at` from `verifier_gate` (FR-2, FR-4, FR-6, FR-7, FR-8) | `scripts/session_analytics/expectations.py` | [x] |
| 3 | The pass: `session-analytics expectations` over both roots, idempotent, refusing a fingerprint mismatch, skipping a ledger with no `init` event or no contract, writing session rows for unmatched ids and resolving them on a later pass (FR-10, FR-11) | `cli.py`, `expectations.py` | [x] |
| 4 | Read surfaces: `GET /api/expectations` (durable, store-only), the MCP tool, `auto_build.py` run detail enriched from the store (FR-12) | `api/server.py`, `mcp/tools.py`, `mcp/server.py`, `api/auto_build.py` | [x] |
| 5 | A4b's compare: run-grain attribution, per-row met/evaluated/unknown/unevaluated + coverage, top-level `runs_spanning_groups` and `runs_with_unmatched_sessions`, rate = met/evaluated or NULL (FR-13) | `api/dashboard.py` | [x] |
| 6 | Tests: normalization incl. waived→unknown and no fictional unwaived skip, statement recovery and each unavailable path, fingerprint collision refusal, roll-up, unevaluated, skip reasons, idempotence, late `session_ref` resolution, `evaluated_at` NULL on failure, aggregate coverage, spanning and unmatched exclusions; the real ledger as a fixture (FR-14) | `tests/test_expectations.py` (incl. the HTTP + MCP contract and run-detail enrichment) | [x] |
| 7 | Studio: the Expectations column with its coverage, `harnessView` rules, states-check; README section incl. the successor note (FR-13, FR-14) | `studio/…`, `scripts/session_analytics/README.md` | [x] |
| 8 | Scratch verification on other ports: the durable `/api/expectations` still answers after a ledger is removed (the run detail correctly does not), and a recovery that fails leaves a stored statement intact; the owner's instance untouched, **no store recreate** | — | [x] |
| 9 | Gates, alignment re-check, `/review-submit`, PR (no close marker), CI green | — | [ ] |
