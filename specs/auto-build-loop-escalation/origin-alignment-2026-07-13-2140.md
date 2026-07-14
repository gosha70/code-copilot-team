# Origin alignment check — auto-build-loop-escalation

Origin: https://github.com/gosha70/code-copilot-team/issues/70

Origin claim:
> Issue #70 (increment C) asks for the human-facing escalation loop on top
> of the merged driver: escalation records with full failure history,
> pluggable notify.command with {feature_id} {reason} {phase} {status}
> {summary} placeholders whose failure never blocks parking, and --resume
> resolution detection from human artifacts (/review-decide outputs, fresh
> origin-alignment record or committed origin-divergence.md, milestone
> sign-off) with exact-missing-artifact refusals and idempotent re-entry.
> It also lists WIP-push-on-escalation for pr/merge profiles.

Working claim:
> specs/auto-build-loop-escalation/{plan.md,spec.md,tasks.md} bind exactly
> that scope (FR-1..FR-10) with one PROPOSED DEVIATION, surfaced for the
> user at plan approval: relocate WIP-push-on-escalation to #71, because no
> pushing profile exists until the pr-profile increment and building it now
> would be unreachable dead code — conflicting with the repo rule that a
> merged PR fully addresses its issue. If the user instead wants WIP-push
> built now behind the profile guard, the bundle will be amended before
> build. No implementation exists yet on branch feat/auto-build-escalation-70.

Verdict: aligned
Confidence: high

Checked 2026-07-13 by re-reading issue #70 (gh issue view 70), the series
design (specs/auto-build-loop/design.md), the merged driver
(scripts/auto-build-loop.sh at f263664), and the freshly authored bundle.
This is Gate 1 (plan approval); plan.md remains status: draft pending user
approval and the WIP-push scope decision.
