---
feature_id: sa-harness-version
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
target_ref: feat/371-a4-harness-version
rounds_completed: 2
attempt_count: 1
bypass: false
---

# Peer Review: sa-harness-version — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 2
**Verdict**: PASS

## Summary

The Round 1 findings are largely addressed: the ISO-shape guard on `recorded_at`, the sticky/COALESCE upsert, the nanosecond-keyed cache, the split `HARNESS_VERSION_MAX_CHARS` vs. ISO regex, and the README sticky-stamp note are all in place and tested. A few residual issues remain — most notably a `_cache` that is still unbounded across paths (the Round 1 concern was only partially resolved), a `harness_mixed` COALESCE that can never clear a stored `FALSE` back to `NULL` on unstamped re-ingest, and a hook that hashes the profile without guarding against special files. None are blocking.

## Findings

- [warning] f-88230675: The Round 1 concern about an unbounded module-level cache was only partially addressed: the cache is now a single entry keyed on `(path, mtime_ns, size)`, which fixes staleness but still means a long-lived MCP server that alternates between two ledgers (or a test suite that creates many temp paths) thrashes the cache on every call — each `read_ledger` for a different path re-parses the whole file. The comment claims "a process reads one ledger", but the adapter is constructed per ingest and the MCP server is long-lived. (scripts/session_analytics/harness_stamps.py)
- [warning] f-79d56931: The `harness_mixed` upsert is `CASE WHEN copilot_session.harness_mixed THEN copilot_session.harness_mixed ELSE COALESCE(excluded.harness_mixed, copilot_session.harness_mixed) END`. Once a row has `harness_mixed = FALSE` (a stamped, unmixed session), a later re-ingest with `raw.harness = None` (ledger pruned) passes `excluded.harness_mixed = NULL`, and `COALESCE(NULL, FALSE) = FALSE` — so the row keeps `FALSE` even though every other fact is now sticky-NULL. That is arguably correct (sticky), but it means `harness_mixed` is not symmetric with the other five columns: a session that was stamped unmixed and whose ledger line is later removed will still report `harness_mixed = FALSE` while `cct_sha` etc. are non-NULL from the earlier ingest. The test `test_a_stored_stamp_is_sticky_when_the_ledger_line_goes_away` covers the mixed-true case but not this one. Confirm the intended semantics and add a test. (scripts/session_analytics/relational/store.py)
- [warning] f-d063a771: The Round 1 finding f-e3de29a0 was marked not-applicable on the grounds that `-f` follows symlinks and is false for a device. That is true for `/dev/zero` (a character device), but `-f` is true for a symlink to a regular file, and `sha256 < "$PROFILE"` on a symlink to a very large regular file (e.g. a multi-GB log) will read the whole thing within the 10 s hook timeout. The hook is bounded, so this is DoS-of-self, but the guard is cheap: `[[ -f "$PROFILE" && -r "$PROFILE" ]]` plus a size cap (e.g. `[[ $(wc -c < "$PROFILE") -lt 1048576 ]]`) would close it. (adapters/claude-code/.claude/hooks/harness-stamp.sh)
- [note] f-a6602d3c: The sort key is `(recorded_at, file_index)`. `recorded_at` is validated to the ISO shape, so lexical sort is correct — good. But the tie-break is file order, and the hook appends, so file order is chronological. If a hand-edited ledger inserts a line out of order with an identical `recorded_at`, file order wins, which is the documented behaviour. No action needed; noting for the record that the tie-break is intentional and tested (`test_a_later_differing_line_marks_mixed_and_keeps_the_earliest` writes out of order). (scripts/session_analytics/harness_stamps.py)
- [note] f-0fa591f1: The Round 1 finding f-6d0da463 was marked not-applicable with the argument that sidechain records carry the same `version` as the parent. That is true for the fixture, but the adapter does not filter sidechain records when collecting `cli_versions` — it iterates every record. If a future CLI ever stamps a subagent with a different version (or a resumed session's sidechain runs under a newer CLI), the parent session will be marked mixed. The current behaviour is defensible, but the code does not encode the assumption; a one-line comment at the collection site ("sidechain records carry the same version as the parent; a difference here is a real mixed session") would make the invariant explicit. (scripts/session_analytics/adapters/claude_code.py)
- [note] f-89a16713: The cache test now exercises a same-second append (size change), which is the realistic case. The documented blind spot (same-size, same-nanosecond rewrite) is not tested — the Round 1 note f-66d98ef3 asked for a test that documents the limitation. A test that rewrites the file with the same size within the same nanosecond is hard to write portably, but a test that asserts the cache key includes `st_mtime_ns` (e.g. by monkeypatching `os.stat`) would document the contract. (scripts/session_analytics/tests/test_harness_stamps.py)
- [note] f-0fcbffa1: The README now states the sticky behaviour, which addresses f-8344f094. It does not state the `harness_mixed` asymmetry noted above (a stored `FALSE` stays `FALSE` even when the ledger line is gone). One sentence would close the loop. (scripts/session_analytics/README.md)
- [note] f-46cc6642: The Round 1 note f-8261fa63 was marked not-applicable because `jq` is optional at setup time. That is a fair call, but the nested `$(...)` quoting is still fragile: if `$version` ever contains a `"` or `\`, the JSON is malformed and the hook will read `null`. The version comes from `package.json`, which is trusted, so this is low-risk — but a `sed`-based escape or a `jq -n` fallback when `jq` is present would be more robust. (adapters/claude-code/setup.sh)
- [note] f-97fb86ec: The six new `_REQUIRED_COLUMNS` entries are correct, but the schema-refusal test (`test_a_schema_9_store_is_refused_with_the_remedy`) constructs a minimal `copilot_session` with only `id, copilot, session_id` — it does not include the other columns the real schema has. The test passes because `check_schema` only checks for the presence of the required columns, but it does not exercise the case where a store has *some* of the six (e.g. a partial migration). A test with a store that has `cli_version` but not `cct_sha` would confirm the refusal is per-column, not per-table. (scripts/session_analytics/relational/db.py)
