# Origin alignment check — auto-build-result-array

- date: 2026-08-08
- trigger: initial gate for the #197 bugfix. Origin read in full this
  session: issue #197 body (summary, repro, captured evidence, offending
  lines 815-818/848-851, proposed fix, acceptance criteria).

## Origin claim (from plan.md)

Normalize array-or-object CLI output to the result element in BOTH
session backends; success advances the phase for both shapes; cost
accrues the real total; session_id chains --resume; PI backend fixed
identically; regression with a 300+-element captured-style array.

## Working claim

session_result_obj() implements exactly the proposed normalization
(type=="result" preferred, .[-1] fallback, legacy object passthrough);
both backends use it; the mock claude defaults to the array shape so
the ENTIRE driver suite exercises it; dedicated regressions cover the
344-element scale, the legacy object, cost accrual, and --resume
chaining via the captured session id.

## Mismatches

none.

Verdict: aligned
Confidence: high
