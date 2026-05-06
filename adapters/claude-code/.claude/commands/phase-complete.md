Signal phase completion. Validates that the review loop has passed (if peer review is enabled) and runs the post-phase checklist.

## Steps

### 1. Gather Context

Determine from the current session:
- `feature_id` — from `specs/*/plan.md` frontmatter or ask the user
- `phase` — `plan` or `build` (infer from current work or ask)
- `subject_provider` — `claude` (this session's provider)
- `peer_provider` — from `CCT_PEER_PROVIDER` env var, or empty for profile default
- `review_scope` — from `CCT_PEER_REVIEW_SCOPE` env var, or `both`
- `target_ref` — current git branch or HEAD commit

### 1.5. Origin Alignment Gate

Run `scripts/check-origin-alignment.sh <feature_id>`.

- Exit 0 — `aligned, high`. Proceed to step 2.
- Exit 1 — `aligned, medium/low`, OR `partial`/`derailed` with a
  fresh committed `specs/<feature_id>/origin-divergence.md`
  (option C from the skill body — the user has acknowledged the
  divergence in writing). Proceed with a recorded warning.
- Exit 2 — `partial`. **Abort.** Surface the three-resolution
  escalation:
  A) rescope the spec to match the origin,
  B) restart from origin,
  C) document the divergence as deliberate
  (`specs/<feature_id>/origin-divergence.md`; once committed and
  newer than the alignment record, the script exits 1 instead).
  Wait for the user to pick A/B/C. Do not proceed to step 2 until
  the script returns exit 0 or 1.
- Exit 3 — `derailed`. Same as exit 2 but stronger language: the
  working artifact delivers something fundamentally different from the
  origin.
- Exit 4 — missing or stale alignment record. Run the
  `origin_alignment_check` procedure from
  `shared/skills/origin-confirmation/SKILL.md` to produce a fresh
  record, then re-run the script.
- Exit 5 — origin frontmatter missing or malformed. Author must add an
  `origin:` block to `specs/<feature_id>/plan.md`; cannot complete
  the phase without it.

This gate is independent of peer review (step 2). Peer review scores
implementation quality; this gate scores origin alignment.

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
