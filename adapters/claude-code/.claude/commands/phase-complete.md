Signal phase completion and trigger peer review (if enabled).

## Steps

### 1. Gather Context

Determine from the current session:
- `feature_id` — from `specs/*/plan.md` frontmatter or ask the user
- `phase` — `plan` or `build` (infer from current work or ask)
- `subject_provider` — `claude` (this session's provider)
- `peer_provider` — from `CCT_PEER_PROVIDER` env var, or empty for profile default
- `review_scope` — from `CCT_PEER_REVIEW_SCOPE` env var, or `both`
- `target_ref` — current git branch or HEAD commit

### 2. Check Review Loop Completion

If `CCT_PEER_REVIEW_ENABLED` is `true`:

**Build phase** — review is gating:
- Check if `.cct/review/loop-summary.json` exists with `verdict: "PASS"` or `bypass: true`.
  - If yes: review completed. Proceed to post-phase checklist.
  - If no: inform the user that peer review has not completed. Tell them to run `/review-submit` before `/phase-complete`.

**Plan phase** — review is advisory:
- If `loop-summary.json` exists, note the verdict but proceed regardless (even on FAIL).
- If `loop-summary.json` does not exist, proceed without review — plan review is optional.
- A plan-phase FAIL is logged but does **not** block `/phase-complete`.

If `CCT_PEER_REVIEW_ENABLED` is not `true`, skip review checks entirely. Proceed to post-phase checklist.

### 3. Run Post-Phase Checklist

Reference the post-phase steps from `phase-workflow.md`:

1. Type/lint check — zero errors
2. Build verification — dev server runs
3. Present summary — files changed, decisions made
4. Commit gate — ask user before committing

### 4. Inform User

Tell the user:
- Phase complete
- If review passed: collaboration artifact at `specs/<feature-id>/collaboration/`
- If review was bypassed: bypass is logged and CI will flag it
