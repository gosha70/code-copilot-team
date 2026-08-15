# Origin Alignment Check — auto-build-conformance-evaluator

Date: 2026-08-13 12:42
Trigger: rev-1 SDD bundle authored for increment C2 (#242), carved out of
#190 at the owner's direction ("carve increment C2 out of #190 and build
it next").

## Origin sources read

- #190 §6 (runtime spec-conformance evaluator, verification block), §3
  (verification.yaml rules: derived requirement, evaluator-unavailable
  fails admission, landed requires every mapped verifier green), §2
  (evaluator invocations metered).
- specs/auto-build-admission/spec.md — Increment-C handoff notes
  (items 1/2/3/4/5); items 3(part)/4 landed in C1, 1/2/5 are C2 per
  specs/auto-build-verification-contract/plan.md "Deliberately NOT in
  this slice".
- #242 (the C2 carrier, created 2026-08-13).

## Working claim

C2 = #190 §6's evaluator + handoff items 1/2/5, on C1's machinery:
config surface with derived `required`, admission availability flip,
frozen conformance contract under C1's pinning rules, driver-owned app
lifecycle, single-invocation landing gate producing a per-FR evidence
ledger (`landed` = every mapped verifier green), reviewer-style metering.
Deferred: visual/C3 (#239), §5 loops, §7, D, and the two unowned
admission DEFER items (recorded on #242).

## Mismatches

- None known at rev 1. #190 §6 sketches `"conformance": { "evaluator":
  "<agent|provider>" }` without an app-launch contract; the plan adds
  `conformance.app` (driver-owned lifecycle) as a derived necessity —
  the evaluator needs a RUNNING app and #190 assigns app startup to no
  one. Flagged here as an addition, not a contradiction.

## Verdict

Verdict: aligned
Confidence: high
