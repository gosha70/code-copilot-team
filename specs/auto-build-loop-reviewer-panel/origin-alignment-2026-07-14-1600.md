# Origin alignment check — auto-build-loop-reviewer-panel

Origin: https://github.com/gosha70/code-copilot-team/issues/78

Origin claim:
> Issue #78 (increment E): specialization-scoped reviewer panel for the
> auto-build driver. One gating reviewer drives the runner-owned round loop
> unchanged; N non-gating reviewers run per phase as advisory — findings
> folded into fix prompts, never blocking PASS or triggering a round, run in
> isolation from the canonical .cct/review/ state. Preflight health-checks all
> reviewers (gating fatal, advisory skip-and-warn). Per-reviewer
> scope/specialization honored + surfaced; all outputs archived per phase.
> Fix the stale providers.toml template comment. Tests cover folding,
> non-blocking, skip-on-unhealthy, isolation, and single-reviewer invariance.
> v1 = one gating + N advisory; multiple gating deferred.

Working claim:
> specs/auto-build-loop-reviewer-panel/{spec.md,plan.md,tasks.md} bind exactly
> that scope (FR-1..FR-10), with three decisions confirmed by the user at plan
> approval (2026-07-14): D-scope = one gating + N advisory (multi-gating
> deferred); D-isolation = a minimal ADDITIVE runner override
> REVIEW_DIR="${CCT_REVIEW_DIR:-$PROJECT_DIR/.cct/review}" (default unchanged,
> existing review-loop tests hold) so advisory reviewers run in scratch dirs —
> the driver still orchestrates; D-advisory-on-clean-pass = advisory findings
> ride gating-triggered fixes only, a clean gating PASS ends the phase. No
> implementation exists yet on branch feat/auto-build-reviewer-panel-78.

Verdict: aligned
Confidence: high

Checked 2026-07-14 by re-reading issue #78, the series design §E + decision 4,
and the current driver review loop + runner review-dir resolution. Plan
flipped to status: approved with explicit user approval; D-isolation
(additive CCT_REVIEW_DIR) and D-scope/D-advisory confirmed.
