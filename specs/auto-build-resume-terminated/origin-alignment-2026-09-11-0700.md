# Origin alignment check — auto-build-resume-terminated

Checked 2026-09-11 07:00, during implementation.

Origin: specs/auto-build-resume-terminated/origin/2026-09-11-owner-request.md
(the owner's request to investigate and address increment D; the
investigation record; run 5's hand-run recovery)

Origin claim:
> Address increment D from the evidence. The one §13 mechanism the data
> supports is a resume of a terminated run — at the review step only,
> when the base is unchanged — because every termination left a green
> build commit that a person then reviewed by hand.

Working claim:
> specs/auto-build-resume-terminated/{spec.md,plan.md,tasks.md} bind
> D2 as FR-1..FR-5: resumable only for provider_unavailable and
> review_breaker, with the history not refusing, the phase's build
> commit still the branch head and the frozen base its ancestor;
> admission with the probe runs again; the termination's records are
> kept under dated names; only the review step runs again; costs
> accumulate against the same cap. Other reasons refuse as before.

Verdict: aligned
Confidence: high

Checked by re-reading the owner's message, the investigation record,
run 5's ledger (build commit 8cfcb90 = branch head at termination),
the driver's two terminated_policy arms, escalation_resumable, the
attended park-resume path and run_phase's build-commit resume.
