# Origin alignment check — auto-build-unattended-core

- date: 2026-08-07 (post Phase-2 re-review + CI P1 fix)
- trigger: spec.md FR-1 amendment — the re-review found FR-1 still said a
  policy-terminated run "remains operator-resumable", contradicting the
  shipped (and reviewer-endorsed) terminal-in-increment-A behavior. The
  FR text now records: terminated_policy is TERMINAL in A, `--resume` on
  a terminated ledger is an explicit refusal, recovery arrives with #190
  increment D. No other requirement changed.

## Origin claim (from plan.md `origin:`, unchanged)

From umbrella #190 (unattended autonomy profile), increment A: "policy
core + metering. Terminal-outcome vocabulary, unattended profile,
disposition dispatch (terminate-only), termination artifacts (§9),
automation-config schema + validator, origin_gate hard rule, full cost
accounting incl. conservative estimates (§2). Nothing runs unattended
before B."

## Working claim (from current spec.md)

Unchanged from the prior record except FR-1's resume clause: a
policy-terminated run is terminal in increment A (explicit `--resume`
refusal; recovery deferred to increment D). This tightens, not loosens,
the origin's "bound, decide, and record — never block" contract: a
silent fall-through re-run would erase the boundary the termination
enforced.

## Mismatches

none — the umbrella's §9 termination-artifact language nowhere promises
resumability of terminated runs; recovery dispositions are explicitly
increment D in the origin.

Verdict: aligned
Confidence: high
