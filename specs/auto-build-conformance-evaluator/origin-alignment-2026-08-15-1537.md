# Origin Alignment Check — auto-build-conformance-evaluator

Date: 2026-08-15 15:37
Trigger: T7 (docs + gates + full sweep) — the completion check before
presenting increment C2 (#242) for merge review.

## Origin sources read

- #190 §6 (runtime spec-conformance evaluator), §3 (verification.yaml
  rules: derived requirement, evaluator-unavailable fails admission,
  landed requires every mapped verifier green), §2 (metering).
- specs/auto-build-admission/spec.md — Increment-C handoff items 1/2/5.
- #242 (the C2 carrier) and the owner's 21 rounds of build-review
  findings (user origin input, 2026-08-13 → 2026-08-15).

## What was built against that origin

- FR-1/FR-2 (T1): `verification.conformance` accepted and closed;
  `required` DERIVED from the finalized artifact, never operator-set.
- FR-3 (T2, handoff item 2): admission screens availability AND
  capability — an evaluator must declare `conformance_command`, because
  reviewer health proves liveness, not the ability to exercise a running
  application.
- FR-4 (T3): the frozen contract spans BOTH verification dimensions and
  is built from one validated capture shared with admission; the
  lifecycle keys on the verification-wide predicate.
- FR-6 (T4): the driver owns the app — launch-bound readiness, bounded
  probes, proven teardown on every path including signals.
- FR-5/FR-7/FR-9/FR-11 (T5, handoff item 1): deterministic verifiers are
  EXECUTED, the evaluator answers through the real provider protocol,
  verdicts must be an exact identity multiset of the frozen criteria,
  evidence is FR → per-verifier, and the checkout may not move across
  the gate.
- FR-8 (T6, handoff items 3/5): evaluator invocations debit the same
  caps as reviewers through the adapter cost channel, with a checked
  ledger write.

## Mismatches

- None outstanding. Two plan-level amendments were made during the build
  and recorded at the time: the unreachable
  `verification.test.timeout_sec` fallback source was dropped
  (origin-alignment-2026-08-13-1803.md), and the rev-2/rev-3/rev-4 plan
  corrections (executed deterministic verifiers, the real provider
  protocol, the capability contract, the resolved app interface) are in
  plan.md with their own records.
- Deliberately deferred, unchanged from the approved plan: visual /
  `skip_is_failure` (#239, C3); §5 bounded progress and multi-round
  evaluator loops; §7 per-phase contracts; §13/D recovery; and the two
  admission DEFER items ("schema-migration allowlist", "mid-flight
  credential/secret enumeration"), which remain UNOWNED and are recorded
  on #242 for a future increment decision.

## Verdict

Verdict: aligned
Confidence: high — every FR in spec.md is implemented and regression-
covered, and the deferrals are the ones the approved plan named.
