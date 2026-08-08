# Origin alignment check — auto-build-unattended-core

- date: 2026-08-07 (post Phase-2 review-fix pass)
- trigger: `plan.md` frontmatter edit (`status: draft` → `approved`) after
  the user's Phase-1 review of PR #192 endorsed the SDD ("The SDD plan
  itself aligns with issue #191: terminate-only increment A, no live
  unattended admission before B, exit 6 terminal semantics, origin-gate
  terminate-only, and full metering are all captured coherently").

## Origin claim (from plan.md `origin:`, unchanged)

From umbrella #190 (unattended autonomy profile), increment A: "policy
core + metering. Terminal-outcome vocabulary, unattended profile,
disposition dispatch (terminate-only), termination artifacts (§9),
automation-config schema + validator, origin_gate hard rule, full cost
accounting incl. conservative estimates (§2). Nothing runs unattended
before B."

## Working claim (from current spec.md, unchanged)

Increment A delivers the terminal-outcome vocabulary (landed /
terminated_policy exit 6 / failed), a fail-closed `unattended` profile
that cannot run before increment B, terminate-only disposition dispatch
at every breaker with mandatory ledger/triage artifacts, the
automation.json schema_version-2 contract + dedicated validator with the
origin_gate locked to terminate in all increments, and full cost
accounting (review rounds metered, conservative flagged estimates)
against the same caps. Attended profiles stay byte-identical.

## Mismatches

none — the only `plan.md` change since the prior record
(origin-alignment-2026-08-07-1641.md) is the `status` frontmatter field
recording the user's approval; no origin source, requirement, or design
content changed.

Verdict: aligned
Confidence: high
