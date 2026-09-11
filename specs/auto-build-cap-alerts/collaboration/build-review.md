---
feature_id: auto-build-cap-alerts
date: 2026-09-10
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feature/auto-build-cap-alerts-run1
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: auto-build-cap-alerts — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The auto-build cap alert feature is well-structured: `auto_build_alerts` is a pure function that derives warning/breach from the same 0.8/1.0 thresholds as budgets, correctly skips concluded runs and null/non-positive caps, and names the estimated portion of cost. Integration points (CLI, both server endpoints, report block, rendered lines) are wired consistently with the documented behavior, and the tests cover boundaries, cap edge cases, one-alert-per-run-per-cap, and report/render semantics. I found no blocking defects; the items below are API-shape consistency, display-precision, and verification notes.

## Findings

- [warning] f-cd30df08: The auto-build alert's `subject` is a dict (`{key, feature_id, ledger, pr_number}`), whereas budget and runaway alerts use a string subject (`_budget_alert(scope: str, subject: str, ...)`). This makes `subject` a heterogeneous field across alert kinds (and `window` shifts from a string to `None`), so any consumer/UI that renders or groups by `subject` as text could display `[object Object]`, crash, or sort inconsistently. (scripts/session_analytics/api/alerts.py)
- [note] f-ef794b63: The displayed percent is `int(round(share * 100))`, so a warning-level run just under the cap (e.g. 9.99/10.0 → 99.9%) renders as "(100%)" while `level` is `warning`, not `breach`. The message and the level can visibly disagree. (scripts/session_analytics/api/alerts.py)
- [note] f-ccaebdea: `now` is accepted only for symmetry and discarded; elapsed time comes from the reader's own clock baked into `elapsed_sec`. This is documented, but it means a caller passing a fixed `now` (as `all_alerts` does for runaway) gets wall-clock alerts evaluated against a different instant than the rest of the report. (scripts/session_analytics/api/alerts.py)
- [note] f-3108b08c: `auto_build_alerts` unit tests use a hand-built run shape (`cost.metered_usd`/`cost.estimated_usd`, `caps.cost_usd`/`caps.wall_clock_sec`, `concluded`, `elapsed_sec`), while the raw ledger (`_live_state`) writes `caps.max_cost_usd`/`max_wall_clock_sec` and `totals.cost_usd`. If `api.auto_build.read_run` does not normalize those keys into the expected names, `caps.get("cost_usd")` is always `None` and no alert ever fires — silently, with no test failure. (scripts/session_analytics/tests/test_alerts.py)
- [note] f-32afd60c: `_run_subject` and the alert message index `run["key"]` directly while every other field uses `.get(...)`. A run record lacking `key` raises `KeyError` instead of degrading gracefully, unlike the rest of the function's defensive handling. (scripts/session_analytics/api/alerts.py)
