# Origin alignment check — auto-build-reviewer-probe

Checked 2026-09-10 09:00, before implementation.

Origin: specs/auto-build-reviewer-probe/origin/2026-09-10-owner-decision.md
(the owner's decision on the D scoping memo; runs 1 and 3 of 2026-09-09)

Origin claim:
> One small request through the actual gating-reviewer path, requiring
> a parseable verdict, before an unattended run builds anything. It
> checks readiness, not review quality. D stays deferred; no new issue,
> no broader recovery design.

Working claim:
> specs/auto-build-reviewer-probe/{spec.md,plan.md,tasks.md} bind that
> as FR-1..FR-6: a `--probe` mode in review-round-runner.sh reusing the
> round's provider resolution, adapter command, sandbox and verdict
> parser; called once from the driver's admission under `unattended`;
> a non-verdict terminates provider_unavailable before a build session;
> the probe is debited as one invocation by the existing rule; no config
> key; attended profiles untouched.

Verdict: aligned
Confidence: high

Checked by re-reading the owner's message, the two failing runs'
termination.json and events, the driver's preflight (providers-health
call at the gating reviewer), the runner's provider resolution and
request template, and scripts/lib/review-verdict.sh.
