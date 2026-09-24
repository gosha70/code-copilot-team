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
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: sa-harness-version — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The A4a harness-stamp slice is well-designed and thoroughly tested: capture-at-SessionStart, earliest-wins-plus-mixed, sticky store semantics, and a single environment control for the ledger path are all correct and pinned by tests. The prior review's three P1/P2 findings (hook registration, re-ingest replacement, JSON-vs-env control) are genuinely fixed. Remaining issues are warnings and notes — a `harness_mixed` asymmetry, an unbounded single-entry cache, and a hook that hashes the profile without a size/symlink guard — none blocking.

## Findings

- [warning] f-3b5b2f2c: Once a row has `harness_mixed = FALSE`, a later re-ingest with `raw.harness = None` passes `excluded.harness_mixed = NULL`; `COALESCE(NULL, FALSE) = FALSE`, so the row keeps `FALSE` while the other five facts are sticky-NULL. This is asymmetric with the other columns and untested. (scripts/session_analytics/relational/store.py)
- [warning] f-c48ca0e4: The cache is a single entry keyed on `(path, mtime_ns, size)`. A long-lived MCP server or a test suite that alternates between two ledger paths re-parses the whole file on every call; the comment "a process reads one ledger" is not true for the MCP server. (scripts/session_analytics/harness_stamps.py)
- [warning] f-39856af3: `-f` is true for a symlink to a regular file, so a symlinked multi-GB file (or a slow network mount) is read in full within the 10 s hook timeout. Bounded self-DoS, but the guard is cheap. (adapters/claude-code/.claude/hooks/harness-stamp.sh)
- [note] f-18da71c5: The adapter iterates every record including sidechain records when collecting `cli_versions`; the invariant "sidechain records carry the same version as the parent" is assumed but not encoded. A future CLI that stamps subagents differently would mark the parent mixed. (scripts/session_analytics/adapters/claude_code.py)
- [note] f-a4c40236: The documented blind spot (same-size, same-nanosecond rewrite) is not exercised; the cache key contract (`st_mtime_ns` included) is not pinned. (scripts/session_analytics/tests/test_harness_stamps.py)
- [note] f-a510af87: The README states the sticky-stamp rule but not the `harness_mixed` asymmetry (a stored `FALSE` stays `FALSE` when the ledger line is later removed). (scripts/session_analytics/README.md)
- [note] f-72273c1b: The nested `$(...)` quoting builds JSON by hand; a `"` or `\` in `$version` (from `package.json`) would produce malformed JSON and the hook would read `null`. Low risk since `package.json` is trusted. (adapters/claude-code/setup.sh)
- [note] f-0bb86b1e: The test constructs a minimal `copilot_session` with only `id, copilot, session_id`; it does not exercise a store that has some of the six new columns (a partial migration). (scripts/session_analytics/tests/test_harness_stamps.py)
