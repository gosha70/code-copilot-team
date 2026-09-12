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
target_ref: feature/runs-attempt-history-recovery
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

The change adds attempt-history fields (probe, earlier terminations, fallbacks) to the auto-build run record, wires them through the Python API, TypeScript types, React view, and states-check. The implementation is generally clean and well-tested, but there are a few correctness concerns around glob matching, sort stability, and the `_fallbacks` phase-key handling that warrant attention.

## Findings

- [warning] f-4c6dd49f: `LEDGER_KEPT_TERMINATION_GLOB = "termination-*.json"` will also match `termination.json` if the driver ever writes a file literally named `termination-<something>.json` that isn't a kept termination, and more importantly it will match any file the driver or a user drops in the ledger with that prefix (e.g. `termination-notes.json`). The current driver only writes `termination-<epoch>.json`, but the glob is unanchored to numeric epochs, so a stray file silently becomes "an earlier termination". (scripts/session_analytics/api/auto_build.py)
- [warning] f-3b56fd33: Sort key is `(e["created"] or "", e["file"])`. If `created` is missing on one entry and present on another, the missing one sorts first (empty string) regardless of actual chronology, and the `file` tiebreaker is a string sort on `termination-<epoch>.json` — which happens to be lexicographically correct only because epochs are the same digit count. A run that spans a digit-count boundary (e.g. 999999999 → 1000000000) would sort wrong. (scripts/session_analytics/api/auto_build.py)
- [warning] f-83a0cbca: `sorted(raw, key=lambda k: _int(k) if _int(k) is not None else 0)` calls `_int(k)` twice per key and coerces non-numeric phase keys to `0`, which would collide with a real phase `0` and produce unstable ordering. If `state["phases"]` ever contains a non-numeric key (e.g. a metadata key), it silently sorts to the front. (scripts/session_analytics/api/auto_build.py)
- [warning] f-e349f42f: `newest` is initialized to `None` and compared with `n > newest`; if the first candidate has `n is None` it's skipped, but if all candidates have unparseable stems, `path` stays `None` and the phase is skipped — correct. However, `candidate.stem[len(C.LEDGER_FINDINGS_PREFIX):]` assumes the stem starts with the prefix; a file like `findings-round-1-extra.json` would yield `1-extra` and `_int` returns `None`, silently dropping it. That's probably fine, but a file named `findings-round-01.json` yields `01` → `1`, which could tie with `findings-round-1.json` and the winner depends on glob order. (scripts/session_analytics/api/auto_build.py)
- [note] f-6bd81183: `str(raw["verdict"]) if raw.get("verdict") else None` — if `verdict` is `0` or `False` (unlikely but possible from a malformed file), it becomes `None` rather than `"0"`/`"False"`. Consistent with the rest of the file's truthiness style, but worth noting. (scripts/session_analytics/api/auto_build.py)
- [note] f-8ed0becb: `bool(raw.get("parseable"))` treats a missing `parseable` as `False`. For a probe file that predates the field, this reports "not parseable" rather than "unknown". The TS type declares `parseable: boolean` (non-nullable), so the UI can't distinguish. (scripts/session_analytics/api/auto_build.py)
- [note] f-55b9c7a7: `p.duration_sec ?? 0` renders `0s` when the probe recorded no duration, which reads as "answered instantly" rather than "duration unknown". The Python `_probe_line` does the same. Minor UX/correctness ambiguity. (studio/lib/runsView.ts)
- [note] f-3b2422b5: `run.outcome ?? \`still ${run.status ?? "running"}\`` — if `outcome` is an empty string (falsy but present), `??` won't catch it and the line reads " after N earlier terminations". The Python side uses `run['outcome'] or 'none'` which handles empty strings. (studio/lib/runsView.ts)
- [note] f-24888ae8: The helper increments `self._written` to avoid ledger-name collisions, but `RESUMED_KEY` is fixed, so multiple `_resumed()` calls in one test produce multiple ledgers with the same key. `scan_runs` presumably dedupes by key — the test `test_hist_fr2_earlier_terminations_are_listed_oldest_first` calls `_resumed` once, but `test_hist_fr1_an_absent_or_unreadable_probe_is_null` calls it after scanning, so ordering matters. Worth a comment or a per-call unique key. (scripts/session_analytics/tests/test_auto_build_runs.py)
- [note] f-941506fc: The cookbook bullet describes the new fields but doesn't mention that `earlier_terminations` excludes the current `termination.json` disposition, which is the subtle part a reader needs to know to interpret "landed after 1 earlier termination". (docs/session-analytics-cookbook.md)
