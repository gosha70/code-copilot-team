# Tasks: the trace tree (A1)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 0 | Owner approves the plan (D1–D4, D2a); greenfield ruling recorded; approved 2026-09-22 after one review round | `plan.md` | [x] |
| 1 | Ingest: `completed_at` on tool results, DDL column, schema version 8, `SchemaMismatch` refusal of a pre-8 store, README remedy (FR-1a, FR-1b) | `contracts.py`, `adapters/claude_code.py`, `relational/store.py`, `relational/db.py`, `config_data/ddl/postgres/001_core.sql`, `README.md` | [x] |
| 1b | Payload: one batched `LEFT JOIN`; tool calls with results, durations under the latency rule, files; unfinished calls kept; `is_sidechain` and `parent_sequence` (FR-1..FR-3, FR-1c) | `scripts/session_analytics/mcp/tools.py` | [x] |
| 2 | Python tests: fixture path; synthetic orphan, error, no-result, and missing/malformed/backward timestamps; version-7 store refused (FR-6) | `scripts/session_analytics/tests/test_mcp_tools.py`, `tests/test_db*.py` | [x] |
| 3 | Studio: `TurnRow` type, `TraceTree` component, Timeline nesting; existing behaviours kept (FR-4, FR-5) | `studio/lib/api.ts`, `studio/components/TraceTree.tsx`, `studio/app/sessions/[id]/page.tsx` | [x] |
| 4 | `states-check` entry for `TraceTree`; README paragraph (FR-6) | `studio/scripts/states-check.mjs`, `scripts/session_analytics/README.md` | [x] |
| 5 | Verify against a scratch store on separate ports; report payload size on the largest session; the owner's store only after they authorize recreating it | — | [x] |
| 6 | Gates, alignment re-check (two owner review rounds folded in), `/review-submit`, PR (no close marker), CI green | — | [ ] |
