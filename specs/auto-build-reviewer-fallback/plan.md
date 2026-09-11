---
spec_mode: lightweight
feature_id: auto-build-reviewer-fallback
risk_category: infra
justification: |
  One bounded retry inside the review runner's existing provider-error
  path, reusing the existing fallback resolution and cost channel; a
  journal event and one debit in the driver. FR-1..FR-4 in spec.md state
  the behaviour.
status: approved
date: 2026-09-11
issue: "#190 D1"
origin:
  transcripts:
    - specs/auto-build-reviewer-fallback/origin/2026-09-11-owner-request.md
  user_messages:
    - "2026-09-11: 'Can we research/investigate and address Increment D …'"
  origin_claim: |
    When the gating reviewer runs and produces no review, send the same
    request once to the next healthy provider in the configured chain
    before the run terminates; record both invocations and which
    provider gated. Scoped from the five runs' evidence; not
    adjudication, not a builder swap.
---

# Plan: reviewer fallback at round time (D1)

## Deliverables

1. `scripts/review-round-runner.sh`: `invoke_reviewer`,
   `provider_failure_message`, `resolve_fallback_provider(subject, skip)`,
   the one-fallback block after the first invocation, `fallback` in the
   findings file, both invocations in the cost state (FR-1, FR-2).
2. `scripts/auto-build-loop.sh`: debit of the failed invocation and the
   `reviewer_fallback` journal event (FR-3);
   `scripts/session_analytics/constants.py`: the event in `POLICY_EVENTS`.
3. Tests in `tests/test-review-loop.sh` and `tests/test-auto-build-loop.sh`;
   pins (FR-4).
4. README: one paragraph under the cost caps section.

## Test strategy

Mock CLI providers in temporary profiles: a primary that exits 1 with an
error line, a fallback that answers PASS (with a marker file proving
whether it ran), a fallback that times out, an unhealthy fallback. The
driver test reuses the probe-answers/round-fails mock from #336.
