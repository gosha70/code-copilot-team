# Origin alignment check — auto-build-loop-pr-profile

Origin: https://github.com/gosha70/code-copilot-team/issues/71

Origin claim:
> Issue #71 (increment D): the `pr` autonomy profile. Profile-gated branch
> push (plain `git push -u origin feature/<id>`, no `--force`, hard refusal to
> push base/master/main); PR creation gated by `scripts/pre-pr-check.sh` then
> `gh pr create` via `$CCT_GH_BIN`, idempotent updates via `gh pr view` ->
> `gh pr edit --body-file` on re-runs/resume, ledger records `pr.number`/
> `pr.url` and resume detects an existing PR instead of duplicating; `gh
> auth status` preflight required iff profile >= pr; WIP-push-on-escalation
> (relocated from #70 by user-approved amendment) pushes the feature branch
> on park in pr/merge while advisory parks locally; tests mock `gh` via a
> `CCT_GH_BIN` argv logger — pr calls `pr create` exactly once across a
> resume cycle, advisory never invokes gh, push-refusal guards covered.
> Depends on #70; `merge` profile and reviewer panel remain later increments
> with config slots reserved.

Working claim:
> specs/auto-build-loop-pr-profile/{spec.md,plan.md,tasks.md} bind exactly
> that scope (FR-1..FR-10), with one user-confirmed decision at plan approval
> (2026-07-14): the PR "Closes #N" target defaults to the feature's own
> origin issue number and is overridable by config `pr.closes`, parking
> (`pr_config`) if neither is available — chosen to satisfy pre-pr-check's
> mandatory title marker while keeping auto-close intent explicit and
> audited. Push cadence is per-phase-gate + finalize-open per the series
> design's `pushing(N)` state. No implementation exists yet on branch
> feat/auto-build-pr-profile-71.

Verdict: aligned
Confidence: high

Checked 2026-07-14 by re-reading issue #71, the series design phasing
(specs/auto-build-loop/design.md §Design/§Safety rails), and the current
driver's profile gate, preflight, park, and finalize sections. Plan flipped
to status: approved with explicit user approval; D1 (close-id sourcing) and
D2 (push cadence) confirmed by the user.
