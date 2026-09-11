---
feature_id: auto-build-reviewer-fallback
date: 2026-09-11
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feat/190-d1-reviewer-fallback
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: auto-build-reviewer-fallback — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The change implements a bounded, single-attempt reviewer fallback at round time, correctly gated on non-zero invocation exit and never overriding a real verdict. The core logic in `review-round-runner.sh` and the driver's debit/journal path look correct, and the test coverage is thorough. I found one correctness concern in the DeepSeek field-rejection heuristic in the adapter that could cause a spurious second request, plus a couple of notes.

## Findings

- [warning] f-c4c4786c: The heuristic for deciding whether the server rejected the DeepSeek `thinking` field is fragile. `[[ "$RESPONSE" == *thinking* && "$RESPONSE" != *chat_template_kwargs* ]]` matches any 400 body containing the substring "thinking" (e.g. an error message like "unexpected field: enable_thinking" or a generic "thinking is not supported" that actually refers to the vLLM field), and the third clause `[[ "$RESPONSE" == *chat_template_kwargs* && "$RESPONSE" == *'"thinking"'* ]]` requires the literal quoted key `"thinking"` which many servers won't echo verbatim. This can drop the DeepSeek field when the server actually rejected the vLLM field, or keep it when the server rejected it — either way the retry may not match the server's complaint. (scripts/provider-adapters/openai-compatible.sh)
- [note] f-8e936c4b: `FALLBACK_COST` is read from `$CCT_REVIEW_COST_FILE` after the first invocation, but `invoke_reviewer` does `rm -f "$CCT_REVIEW_COST_FILE"` at its start. The read happens before the second `invoke_reviewer` call, so it is correct today — but the ordering is subtle and a future refactor that moves the read after the fallback invocation would silently lose the failed invocation's cost. A brief comment noting the read must precede the second `invoke_reviewer` would harden this. (scripts/review-round-runner.sh)
- [note] f-461d2efb: The "both fail" test asserts `provider_error.message` equals `"timed out after 7s (after 'mock' failed first: Error: primary is broken)"`, which depends on the fallback's `exit 124` being interpreted as a timeout. This is correct given `provider_failure_message`, but the test does not cover the case where the fallback fails with a non-timeout, non-empty error — the concatenation path is exercised only via the timeout branch. Adding a variant where the fallback exits 1 with a message would pin the general concatenation behavior. (tests/test-review-loop.sh)
- [note] f-3b13b9bc: The driver reads `.fallback.invocation_cost_usd` and passes it to `debit_invocation_cost`, but if the field is `null` (unmetered), `_fb_cost` becomes empty and the debit falls through to the estimate path — consistent with the primary path. However, the journal message does not distinguish metered vs estimated for the failed invocation, while the README claims "Both invocations are debited" without qualifying. This is a documentation nuance rather than a bug, but worth a one-line clarification in the README that the failed invocation may be debited as an estimate. (scripts/auto-build-loop.sh)
