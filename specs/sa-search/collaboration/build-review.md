---
feature_id: sa-search
date: 2026-09-23
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feat/371-a2-search
rounds_completed: 2
attempt_count: 1
bypass: false
---

# Peer Review: sa-search — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 2
**Verdict**: PASS

## Summary

Round 2 addresses the Round 1 findings well: the malformed-date case now raises `InvalidDateError` mapped to 400, the label filter reads `load_rubric().name` (with a test that inserts under the real name), and the MCP wrapper forwards every filter with a contract test. The remaining concerns are mostly about the correlated priced-cost subquery's fragility, the per-request facet cost, and a few smaller correctness/robustness items.

## Findings

- [warning] f-9e3a951c: The priced-cost subquery is correlated on `copilot_session.id` and is inlined into `_session_filters`, which is also used by `count_noise_sessions`. If any future caller aliases `copilot_session` (as the Round 1 finding f-689047a3 noted), the correlated reference breaks silently and the filter matches nothing. The current code works only because the alias happens to match. (scripts/session_analytics/mcp/tools.py)
- [warning] f-8c79d806: `session_facets` runs three unbounded `SELECT DISTINCT` scans (including a join through `copilot_tool_call`/`copilot_turn`) on every `/api/sessions` request. The Round 1 finding f-60435218 was marked not-applicable based on a 158-session measurement, but the plan itself flags this as a risk with a fallback (separate cached route) that is not implemented. On a store with millions of tool calls this is a per-request cost that scales with table size. (scripts/session_analytics/mcp/tools.py)
- [warning] f-d12013eb: `_valid_date` normalises a timestamp to `%Y-%m-%dT%H:%M:%S.%fZ` with millisecond precision, but `datetime.fromisoformat` accepts inputs with microsecond precision (e.g. `2026-09-22T23:59:00.123456Z`). The truncation to milliseconds is silent, so a caller passing a microsecond-precision bound gets a subtly different comparison than they wrote. Also, a naive timestamp (no tzinfo) is returned as-is without being treated as UTC, which may not match the stored shape. (scripts/session_analytics/mcp/tools.py)
- [warning] f-7574f345: Round 1 finding f-4abc34d4 flagged that `float(min_cost)` raises `ValueError` on a non-numeric string, surfacing as a 500 rather than a 400. The fix was not applied: `float(min_cost)` is still called directly in `_session_filters`, and the API route's `Optional[float]` coercion only covers the HTTP path — the MCP tool path can still pass a string. (scripts/session_analytics/mcp/tools.py)
- [note] f-097f77e9: `_day_after` says "The caller has validated the day", but it is called from `_session_filters` after `_valid_date` returns a 10-char string. If `_valid_date` ever returns a 10-char string that is not a valid ISO date (it cannot today, but the invariant is implicit), `date.fromisoformat` raises `ValueError` uncaught. The invariant is fine but undocumented at the call site. (scripts/session_analytics/mcp/tools.py)
- [note] f-fe97d604: The `col` helper filters out `None` and `""` but not whitespace-only strings, so a session with `model="   "` would appear as a facet option. Minor, but inconsistent with the "blanks omitted" contract in FR-4. (scripts/session_analytics/mcp/tools.py)
- [note] f-ac3f2e26: Round 1 finding f-e4939977 flagged that `_tool_rows` is defined after the `if __name__ == "__main__"` block, so running the test file directly fails with `NameError`. The fix was not applied; the function is still below the `unittest.main()` call. (scripts/session_analytics/tests/test_mcp_tools.py)
- [note] f-0bc8b761: The README says "an unknown tag or label is a 400" but does not mention that a malformed `date_from`/`date_to` is also a 400 (Round 1 finding f-638027a8 was about the old silent-ignore behavior; the behavior changed but the doc was not updated to say so). (scripts/session_analytics/README.md)
- [note] f-1ad75ab1: Round 1 finding f-905bea8e flagged the `# noqa: E731` lambda-assignment pattern; it is still present in `archive_coverage`. A `def` would be cleaner and avoid the noqa. (scripts/session_analytics/mcp/tools.py)
- [note] f-ab9d3c24: Round 1 finding f-7aab683e flagged the breaking signature change from positional `(query, copilot, ...)` to `(filters, ...)`. The change is still breaking with no deprecation path. The owner's green-field ruling covers data, not the Studio's internal API surface, but external callers (if any) would break. (studio/lib/api.ts)
- [note] f-ee4143ca: `Number(v)` accepts `"Infinity"` and `"1e999"` (which becomes `Infinity`), and `Number.isFinite` rejects them, so they are dropped — correct. But `Number("")` is `0`, and the empty-string check happens before the numeric branch, so this is fine. Round 1 finding f-8e5aa79e noted this; no action needed, but a comment would help future readers. (studio/lib/filterView.ts)
