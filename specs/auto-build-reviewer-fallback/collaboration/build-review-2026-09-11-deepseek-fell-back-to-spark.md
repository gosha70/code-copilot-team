---
feature_id: auto-build-reviewer-fallback
date: 2026-09-11
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: spark
peer_profile: spark
runner_fingerprint: 303af47027968338139fc2247d24c612c9d02c71c6e4893b1dd3c2431e6f770d
verdict: PASS
blocking_findings_open: 0
target_ref: feat/190-d1-reviewer-fallback
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: auto-build-reviewer-fallback — Build Phase

**Reviewer**: spark
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The implementation correctly introduces a bounded, single-attempt reviewer fallback mechanism that triggers only when the primary reviewer produces no review (non-zero exit), ensuring that valid verdicts (PASS/FAIL) are never overridden. The cost accounting and journaling logic are robust, correctly handling both metered and unmetered invocations for both the failed and fallback providers. The changes are well-tested with comprehensive edge cases covering fallback success, fallback failure, and unhealthy fallbacks.

## Findings

- [note] f-85878546: The `invoke_reviewer` function relies on global variables `REVIEW_OUTPUT` and `REVIEW_EXIT` which are set within the function. While this works in the current script structure, it is a side-effect-heavy pattern. If `invoke_reviewer` were ever called in a subshell (e.g., `$(invoke_reviewer)`), the variables would not propagate back to the parent scope. Currently, it is called directly, so this is safe, but worth noting for future refactoring. (scripts/review-round-runner.sh)
- [note] f-d5a6a877: The driver logic checks `[[ $_debit_rc -eq 0 && -n "${post_frf:-}" ]]` before processing the fallback debit. This ensures that if the primary debit failed, the fallback debit is skipped, and the subsequent `if [[ $_debit_rc -ne 0 ]]` block will trigger the `cost_accounting_failed` disposal. This is correct behavior: if we can't record the primary cost, we shouldn't try to record the fallback cost, and we should halt. (scripts/auto-build-loop.sh)
- [note] f-076d6eaa: The test for "Both fail" asserts that `reviewer_provider` is "spare" (the fallback) when both fail. This is consistent with the logic that `PEER_PROVIDER` is updated to the fallback before the second invocation. The `provider_error` message correctly concatenates the fallback's error with the primary's error. This is a good design choice for debugging. (tests/test-review-loop.sh)
- [note] f-9d125677: The README update clearly explains the new behavior and its rationale. It correctly states that "A verdict from the first provider is final — the chain exists for 'no review', never for a second opinion." This aligns with the implementation. (README.md)
