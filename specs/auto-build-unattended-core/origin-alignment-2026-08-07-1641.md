# Origin alignment check — auto-build-unattended-core

Origin: https://github.com/gosha70/code-copilot-team/issues/191
(child of https://github.com/gosha70/code-copilot-team/issues/190)

Origin claim:
> Umbrella #190 increment A: policy core + metering. Terminal-outcome
> vocabulary (landed / terminated_policy / failed, distinct from the
> resumable parked), the unattended profile, disposition dispatch
> (terminate-only), termination artifacts, automation-config schema +
> validator, the origin_gate never-auto-resolve hard rule, and full cost
> accounting including conservative estimates — every driver-initiated
> invocation debits caps.cost_usd, review rounds included (today they are
> unmetered). Nothing runs unattended before increment B.

Working claim:
> The spec binds exactly that scope to verified code anchors (12 park
> reasons, cost debits only at the two build-session sites, zero cost
> accounting in review-round-runner.sh, exit codes 0/1/3/4 in use → 6
> free): FR-1 outcomes + exit 6, FR-2 the profile with a fail-closed
> preflight until B, FR-3 terminate-only dispatch, FR-4 the origin_gate
> lock (schema-enforced), FR-5 best-effort termination artifacts that
> never weaken prechecks, FR-6 schema v2 + a dedicated validator (not
> validate-cct-config.sh, per the umbrella), FR-7 full metering with
> flagged conservative estimates against the same cap and explicit-caps
> enforcement, FR-8 the cooldown-supervisor terminal rule with a test,
> FR-9 byte-identical attended profiles. B/C/D/E machinery is explicitly
> out of scope.

Mismatches:
  - none

Verdict: aligned
Confidence: high
