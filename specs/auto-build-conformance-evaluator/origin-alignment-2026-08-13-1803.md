# Origin Alignment Check — auto-build-conformance-evaluator

Date: 2026-08-13 18:03
Trigger: build-time plan amendment during the round-2 build review
(T1–T3 implementation, findings 1–4). One normative correction to the
approved plan; scope unchanged.

## Amendment

Plan decision 4's verifier-timeout fallback chain named
`verification.test.timeout_sec` as the first source. That source is
unreachable — `validate-automation-config.sh` rejects
`verification.test` by name (C1's single-source rule for the test
step) — so the frozen `verifiers.timeout_sec` comes from
`test.timeout_sec` alone. Documented in the plan rather than left as an
inert setting (the #205/#212 lesson admission itself encodes).

## Round-2 corrections (implementation-level, no plan change)

- Freezing goes through ONE validation-and-capture path
  (`vc_capture_from_parsed`): admission hands the driver the capture
  from the very parse it validated; attended initialisation runs the
  same function and refuses on drifted/uncovered artifacts. This
  implements plan decision 4's freeze; it does not alter it.
- A missing parser helper is an installation error (fail closed), and
  the preflight-result schema scopes C1 coverage rules under a
  presence conditional — both consistency fixes to T3's own machinery.

## Verdict

Verdict: aligned
Confidence: high — the amendment removes an unreachable config source;
every other correction tightens the implementation toward the approved
contract.
