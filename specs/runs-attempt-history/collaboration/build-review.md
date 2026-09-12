---
feature_id: runs-attempt-history
date: 2026-09-12
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: master
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: runs-attempt-history — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The change adds attempt-history fields (probe, earlier terminations, fallbacks) to the auto-build run record and wires them through the Python API, TypeScript types, React view, and states-check. The implementation is well-tested and the Python/TS renderers are kept in sync. I found one correctness issue worth flagging (the `_fallbacks` round-number parsing can silently drop or mis-tie rounds) and several notes; nothing rises to blocking.

## Findings

- [warning] f-5109b4a8: The stem slice assumes the file name is exactly `findings-round-<n>.json`. A file like `findings-round-01.json` yields `"01"` → `1`, which ties with `findings-round-1.json`; the winner then depends on `glob` order, so the "newest round" is nondeterministic. A file like `findings-round-1-extra.json` yields `"1-extra"` → `None` and is silently dropped even though it is a round file. (scripts/session_analytics/api/auto_build.py)
- [note] f-749bce45: The primary sort key is the `created` string, with the epoch as tiebreaker. If one record has `created` and another does not, the missing one falls back to `_iso(epoch)` (a string), so the two are compared as strings — fine when both are ISO-8601 UTC, but a record with a non-ISO `created` (e.g. a local-time string) would sort incorrectly against the epoch-derived fallback. (scripts/session_analytics/api/auto_build.py)
- [note] f-d1d245d8: A probe file that predates the `parseable` field reports `false` ("not parseable") rather than "unknown". The TS type declares `parseable: boolean` (non-nullable), so the UI cannot distinguish "explicitly false" from "field absent". (scripts/session_analytics/api/auto_build.py)
- [note] f-4884bef7: \ (studio/lib/runsView.ts)
- [note] f-97b564b5: `RESUMED_KEY` is fixed while `self._written` only varies the ledger directory name, so multiple `_resumed()` calls in one test produce multiple ledgers with the same run key. `scan_runs` presumably dedupes by key, but which ledger wins depends on scan order — a latent source of flakiness if a future test calls `_resumed()` twice with different `extra` and expects the second to win. (scripts/session_analytics/tests/test_auto_build_runs.py)
- [note] f-d2e02170: The bullet says a resumed run "reads as 'landed after 1 earlier termination'", but does not state that `earlier_terminations` excludes the current `termination.json` disposition. That exclusion is the subtle part a reader needs to interpret the count correctly. (docs/session-analytics-cookbook.md)
