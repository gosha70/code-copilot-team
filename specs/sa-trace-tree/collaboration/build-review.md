---
feature_id: sa-trace-tree
date: 2026-09-22
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feat/371-a1-trace-tree
rounds_completed: 2
attempt_count: 1
bypass: false
---

# Peer Review: sa-trace-tree — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 2
**Verdict**: PASS

## Summary

The Round 1 findings are largely addressed: `_has_column`/`_has_table` now filter on `current_schema()`, `schema_version` is guarded before querying, `has_result` is derived from the result row's id, and `SchemaMismatch` is threaded through `create_app` and every CLI handler to a single exit path. The new trace-tree payload, Studio component, and tests are coherent and additive. A few residual issues remain around the cycle-guard logic in `nestTurns`, the `duration_seconds` semantics, and some minor robustness/UX details.

## Findings

- [warning] f-5391aae1: The cycle guard is fragile: when a cycle is detected, `cur` becomes `undefined` only because the parent is already in `seen`, so the loop exits with `anchor = null` and the turn falls to top level. This happens to produce `0[] 1[] 2[]` for a 2-cycle, but the logic is not obviously correct for longer cycles or when the entry point is not the cycle head — the walk relies on the `seen` set to terminate rather than on an explicit "cycle detected" branch, and the resulting anchor is whatever `cur` happens to be when the loop exits. The states-check only exercises a 2-cycle. (studio/lib/traceView.ts)
- [warning] f-4d73f0fe: `duration_seconds` is `completed_at − turn.timestamp`, i.e. the wall time from the turn's own timestamp to the result record. For a turn with multiple calls issued at different times, all durations share the same start, so the field name and the UI label "until result" can mislead a reader into thinking it is per-call latency. The spec and README acknowledge this, but the field name in the API payload (`duration_seconds`) does not carry the caveat. (scripts/session_analytics/mcp/tools.py)
- [note] f-5a6b7f96: The fold keys on `call_id` and appends the call to `turn["tool_calls"]` on first sight. If the same `call_id` ever appears under two different `turn_id`s (should not happen given the schema, but the query does not enforce it), the second turn would silently miss the call. The `turn is None: continue` branch also silently drops rows whose turn is not in `by_turn_id`, which could hide a data-integrity problem. (scripts/session_analytics/mcp/tools.py)
- [note] f-fd89bd14: `SELECT MAX(version) FROM schema_version` is now guarded by `_has_table(db, "schema_version")`, which is good. But the query itself is not wrapped against a `schema_version` table that exists with an unexpected shape (e.g. no `version` column). A partial store could still raise a raw DB error instead of `SchemaMismatch`. Low likelihood, but the whole point of this path is to produce the remedy message. (scripts/session_analytics/relational/db.py)
- [note] f-7e9c86b1: The pattern is repetitive and easy to forget when a new handler is added. The comment in `main()` explains the intent, but a future handler that catches `Exception` before `SchemaMismatch` would silently swallow the refusal. (scripts/session_analytics/cli.py)
- [note] f-f28849cc: The test imports `create_app` inside a try/except ImportError, so on a machine without FastAPI the API half is skipped without any signal. A regression in `create_app`'s exception handling could go unnoticed if the import path changes. (scripts/session_analytics/tests/test_db_dialect.py)
- [note] f-f797ed14: The README says the DDL is create-if-absent and cannot add a column, and gives the remedy, but does not say that the refusal happens at `apply_ddl` time — i.e. on any command that opens the store, including read-only ones like `kpis`. A user running `kpis` against an old store will get the recreate message, which may be surprising. (scripts/session_analytics/README.md)
- [note] f-6f24824e: `untilResult(c)` is invoked once in the condition and once in the body of the JSX. Minor, but a local `const d = untilResult(c)` would be cleaner and avoid a redundant call. (studio/components/TraceTree.tsx)
- [note] f-f61881a1: When `c.status` is a non-empty string that is neither "success" nor "error" (e.g. "timeout"), the label uses the emerald tone, which visually implies success. The status text is shown, but the color is misleading. (studio/components/TraceTree.tsx)
