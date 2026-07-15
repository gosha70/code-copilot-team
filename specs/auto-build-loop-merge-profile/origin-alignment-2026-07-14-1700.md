# Origin alignment check — auto-build-loop-merge-profile

Origin: https://github.com/gosha70/code-copilot-team/issues/80

Origin claim:
> Issue #80 (increment F, final): the `merge` autonomy profile. Everything `pr`
> does plus a gated auto-merge — `merge.enabled` (default false) is the final
> switch (false → behaves as `pr`); when enabled + require_branch_protection,
> verify base branch protection via `gh api .../branches/{base}/protection` and
> park (merge_blocked) if unprotected; arm GitHub-native `gh pr merge <n>
> --auto --<method>` (method default squash) so GitHub merges only when the
> branch-protection required checks pass (delegating require_green_ci); ledger
> records auto_merge_armed/merge_method and resume never re-arms; the driver
> never merges locally, never forces, never commits/pushes to the base;
> advisory/pr never invoke pr merge. Completes the series A–F.

Working claim:
> specs/auto-build-loop-merge-profile/{spec.md,plan.md,tasks.md} bind exactly
> that scope (FR-1..FR-8), with four decisions confirmed by the user at plan
> approval (2026-07-14): D-mechanism = GitHub-native `gh pr merge --auto` (the
> driver never polls CI or merges locally; the gate is GitHub branch
> protection); D-enabled-false = `merge` behaves as `pr` when enabled is false;
> D-method = squash default; D-protection-absent = park merge_blocked
> (fail-closed) when require_branch_protection and the base is unprotected. No
> implementation exists yet on branch feat/auto-build-merge-profile-80.

Verdict: aligned
Confidence: high

Checked 2026-07-14 by re-reading issue #80, the series design §F + Finalize +
Safety rails, and the current driver's profile ladder + finalize/open_or_update_pr
+ gh preflight. Plan flipped to status: approved with explicit user approval;
D-mechanism (native --auto) and D-enabled-false/D-method/D-protection-absent
confirmed.
