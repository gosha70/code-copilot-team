---
feature_id: sa-expectations
date: 2026-09-24
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feat/371-a5-expectations
rounds_completed: 2
attempt_count: 1
bypass: false
---

# Peer Review: sa-expectations — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 2
**Verdict**: PASS

## Summary

Round 2 review of the sa-expectations slice. The builder's resolutions to Round 1 are largely sound: the stale-result deletion (f-2d9bf85c) is a real fix with a regression test, the fail-safe normalization inversion is correct, and the statement-durability guard is well-reasoned. I found one new correctness issue in the run-detail enrichment path and a few smaller concerns.

## Findings

- [warning] f-81ebf68e: `run.get("key")` is used as `attempt_id`, but the run detail is keyed by `attempt_id` alone while the store's identity is the composite `(feature_id, attempt_id)`. If `run["key"]` is not literally the ledger's `attempt_id` (e.g. it is a display key or a composite), the lookup silently returns None and the enrichment is lost with no signal. The docstring says None means "never ingested", so a key-shape mismatch would be indistinguishable from that. (scripts/session_analytics/api/auto_build.py)
- [warning] f-a264a150: `recover_statements` is called once per run inside `_store_run`, and it shells out to `git show` plus `bash -c` for every run on every pass. On a ledger root with many archived runs this is O(runs) subprocess pairs per invocation, and the pass is documented as idempotent and re-runnable. There is no caching of the recovered spec text per `(project, feature_id, branch_base_ref)`. (scripts/session_analytics/expectations.py)
- [warning] f-68b507a8: When `existing is not None` and the fingerprint matches, the code updates `status`, `outcome`, `evaluated_at`, `ledger_path`, `ledger_root` but never `contract_fingerprint` or `branch_base_ref`. If the ledger's contract or base ref changed under the same fingerprint (which the fingerprint is supposed to prevent, but the fingerprint is computed from the *current* ledger, not the stored one), the stored `contract_fingerprint`/`branch_base_ref` can silently diverge from the stored `run_fingerprint`. The fingerprint check compares the incoming fingerprint to the stored one, so a divergence here would mean the stored fingerprint no longer describes the stored row. (scripts/session_analytics/expectations.py)
- [warning] f-321926d0: The DELETE-then-INSERT/UPDATE pattern is not wrapped in a transaction and relies on `db.commit()` at the end of `ingest_runs`. If a later run in the same pass raises (e.g. a DB error), the earlier runs' deletes and inserts are rolled back together — which is fine — but if the process is killed mid-pass, the store is left with a partially-applied run. More concretely: the DELETE removes ordinals `>= len(rows)` before the loop, so if the loop raises on ordinal 0, the tail is already gone and the head is not yet written. (scripts/session_analytics/expectations.py)
- [note] f-5d5bb89b: The promotion logic decrements `stats.statements_unavailable` and increments `stats.statements_recovered` when a stored recovered statement is preserved. But the counters were already incremented earlier in the same iteration (the `if source == RECOVERED: ... else: ...` block runs before the row lookup). So the net effect is correct, but the code reads as if it is double-counting. A comment would help. (scripts/session_analytics/expectations.py)
- [note] f-e7d07cdb: `refs = [s.get("session_ref") for s in links]` then `placed = {group_of_session.get(ref) for ref in refs if ref is not None}`. If `session_ref` is present but not in `group_of_session` (e.g. the session exists in the store but was filtered out of the harness population by the sessions query), `group_of_session.get(ref)` returns None and the run is counted as `unmatched`. That is the intended behavior per the docstring, but the `unmatched` counter conflates "session not in store" with "session in store but outside the population". The exclusion note in the UI does name both causes, so this is consistent — noting for completeness. (scripts/session_analytics/api/dashboard.py)
- [note] f-34ae9136: The invariant `bool(has_results) == (evaluated_at is not None)` is asserted over real ledgers. This holds for the current driver, but if a future driver writes a `verifier_gate` event on a failing run (or writes results without a gate), this test fails for a reason unrelated to the code under review. It is a canary, which is arguably the point, but it couples the test to driver behavior. (scripts/session_analytics/tests/test_expectations.py)
- [note] f-c50e0c8b: The README says "only 3 of 85 spec bundles carried a `verification.yaml`" and "only a run admitted under the unattended profile has a contract to freeze — those counts move as the repository does." The date is given ("As measured on 2026-09-25") which addresses the Round 1 note, but the counts are still presented as facts without a pointer to how they were measured. (scripts/session_analytics/README.md)
- [note] f-329c4cca: `limit=None` is the sentinel for "no limit". The docstring explains this, but a caller passing `limit=0` would get `LIMIT 0` (zero rows) rather than an error, and a caller passing a negative limit would get a SQL error. The HTTP and MCP surfaces clamp, but the internal API does not. (scripts/session_analytics/expectations.py)
- [note] f-accb9e19: The function is long (~80 lines) and mixes identity resolution, statement recovery, expectation upsert, result upsert, and session upsert. The docstring on `ingest_runs` describes the contract, but `_store_run` itself has no docstring. (scripts/session_analytics/expectations.py)
