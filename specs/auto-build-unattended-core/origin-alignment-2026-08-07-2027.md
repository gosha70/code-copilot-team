# Origin alignment check — auto-build-unattended-core

- date: 2026-08-08 (post Phase-3 review-fix pass)
- trigger: spec.md FR-9 amendment recording the reviewer-verified FR-7
  carve-out — a reviewer backend that genuinely reports measured cost
  now debits `caps.cost_usd` on every profile (previously silently
  free). Estimates remain opt-in for attended configs and inactive for
  v1. No other requirement changed.

## Origin claim (from plan.md `origin:`, unchanged)

From umbrella #190 (unattended autonomy profile), increment A: "policy
core + metering. Terminal-outcome vocabulary, unattended profile,
disposition dispatch (terminate-only), termination artifacts (§9),
automation-config schema + validator, origin_gate hard rule, full cost
accounting incl. conservative estimates (§2). Nothing runs unattended
before B." — "a $100 cap must mean $100 — review rounds, currently
unmetered, must debit the same budget."

## Working claim (from current spec.md)

Unchanged from the prior record except FR-9's byte-identical clause now
names the deliberate carve-out: measured review costs debit the cap on
all profiles. This follows the origin directly — "every driver-initiated
invocation metered or conservatively estimated against the SAME cap" is
FR-7's global rule; exempting attended profiles from MEASURED costs
would preserve the exact under-counting the origin calls out.

## Mismatches

none — the carve-out implements the origin's own §2 demand; the
byte-identical guarantee was always scoped to behavior absent new
information, and a backend reporting real cost is new information.

Verdict: aligned
Confidence: high
