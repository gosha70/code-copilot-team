# Origin Alignment Check — auto-build-conformance-evaluator

Date: 2026-08-13 14:14
Trigger: rev-2 holistic correction pass on PR #243 after the owner's plan
review of rev 1 (4 P1 + 1 P2 findings, verdict "Request changes — one
holistic correction pass"). Supersedes the rev-1 record (renamed to its
true authoring time, `origin-alignment-2026-08-13-1242.md` — its
filename had claimed 18:00).

## Origin sources read

- #190 §6 (runtime spec-conformance evaluator), §3 (verification.yaml
  rules: derived requirement, evaluator-unavailable fails admission,
  landed requires EVERY mapped verifier green), §2 (metering).
- specs/auto-build-admission/spec.md — Increment-C handoff notes; item 1
  "C owns the real verifier decision".
- specs/auto-build-verification-contract/plan.md — "Deliberately NOT in
  this slice" (C2 enumeration).
- #242 (the C2 carrier) and the owner's rev-1 review findings (user
  origin input, 2026-08-13).

## Working claim

Unchanged from rev 1: C2 = #190 §6's evaluator + handoff items 1/2/5 on
C1's machinery. Rev 2 corrects HOW the claim is satisfied (below); it
does not change scope.

## Mismatches found at rev 1 — corrected in rev 2

- **Deterministic verifiers were inferred, not executed (P1).** Rev 1's
  FR-7 marked `kind: deterministic` entries green iff the generic
  `test.command` gate passed. That contradicts the origin: #190 §3's
  "landed requires every mapped verifier green" and handoff item 1's "C
  owns the real verifier decision" require each verifier's OWN frozen
  command to run and pass at the gate. Rev 2 freezes the deterministic
  set (`verifiers`) and executes every verifier at the landing gate,
  with per-verifier results in `verification-results.json`.
- **The contract lifecycle predicate was coverage-only (P1).** Rev 1
  left the preflight paths keyed on `HAS_COVERAGE_BLOCK`, so a
  conformance-only run could bypass freeze/resume machinery. Rev 2 keys
  the lifecycle on the verification-wide predicate (plan decision 3);
  tasks.md T3 names the change.
- **Evaluator verdicts were not identity-bound (P1)** — rev 2 requires
  the full frozen-tuple echo and exact multiset validation, plus
  C1-style result freshness.
- **No checkout-integrity invariant around gate execution (P1)** — rev 2
  adds clean-before/clean-after with captured gate HEAD (`git_anomaly`
  on mutation; FR-11).
- **No evaluator-visible frozen app interface; readiness could be vouched
  by a stale responder (P2)** — rev 2 adds `CCT_CONFORMANCE_APP` and the
  group-alive-at-readiness requirement.
- The rev-1 record's "Mismatches: None known / Confidence: high" was
  wrong while these findings stood; this record supersedes it.

## Standing addition (unchanged from rev 1)

#190 §6 sketches `"conformance": { "evaluator": … }` without an
app-launch contract; `conformance.app` (driver-owned lifecycle) remains
a derived necessity, not a contradiction.

## Verdict

Verdict: aligned
Confidence: high — the deterministic-verifier conflict is resolved by
execution at the gate; the remaining delta from #190's sketch is the
app-launch contract, an addition the origin leaves unassigned.
