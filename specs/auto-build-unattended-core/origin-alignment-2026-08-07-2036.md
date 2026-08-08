# Origin alignment check — auto-build-unattended-core

- date: 2026-08-08 (post Phase-3 re-review PASS)
- trigger: spec.md gains an "Increment-B preconditions" subsection
  recording the two review-accepted increment-A residuals as hard
  preconditions for #190 increment B (out-of-band cost channel; honest
  finalize under gh capability downgrade), per the reviewer's condition
  and the repo's single-source-of-truth rule. No requirement of
  increment A itself changed.

## Origin claim (from plan.md `origin:`, unchanged)

From umbrella #190 (unattended autonomy profile), increment A: "policy
core + metering. Terminal-outcome vocabulary, unattended profile,
disposition dispatch (terminate-only), termination artifacts (§9),
automation-config schema + validator, origin_gate hard rule, full cost
accounting incl. conservative estimates (§2). Nothing runs unattended
before B."

## Working claim (from current spec.md)

Unchanged from the prior record; the new subsection constrains increment
B, not A — it records that both accepted residuals are safe only while
unattended stays fail-closed, which is itself the origin's "Nothing runs
unattended before B" rule.

## Mismatches

none.

Verdict: aligned
Confidence: high
