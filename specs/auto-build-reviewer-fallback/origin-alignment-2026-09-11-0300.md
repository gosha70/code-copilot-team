# Origin alignment check — auto-build-reviewer-fallback

Checked 2026-09-11 03:00, during implementation.

Origin: specs/auto-build-reviewer-fallback/origin/2026-09-11-owner-request.md
(the owner's request to investigate and address increment D; the
investigation record over five runs; the owner's request that DeepSeek
review the work)

Origin claim:
> Address increment D from the evidence: every provider failure was the
> reviewer, the builder finished every phase, and a configured healthy
> fallback was never asked because the chain is consulted only at
> healthcheck time. Recover at the point the data names — the round —
> not with a builder swap or an adjudicator the data never called for.

Working claim:
> specs/auto-build-reviewer-fallback/{spec.md,plan.md,tasks.md} bind
> D1 as FR-1..FR-4: one fallback per round on a non-zero invocation,
> the same request, the existing chain, the failed provider never its
> own fallback, a verdict always final, both invocations recorded and
> debited, the switch journaled as a policy decision. D2 follows
> separately; adjudication and builder swap stay design text.

Verdict: aligned
Confidence: high

Checked by re-reading the owner's two messages, the investigation
record, the three terminated ledgers' termination.json and the
providers.toml backups at each run, the runner's provider-error path
(#204) and fallback resolution, and the driver's debit rule (#336).
