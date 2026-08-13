Resolve a circuit breaker in the review loop. Accepts exactly one argument: approve, reject, or retry.

## Usage

```
/review-decide approve
/review-decide reject
/review-decide retry
```

## Prerequisites

- A live breaker: either `.cct/review/breaker-tripped.json` exists, **or**
  an unresolved `review_breaker` escalation exists for THIS feature
  (bound via `.cct/review/state.json`'s `feature_id`) — a crash can park
  the run without ever writing the breaker file (#233)
- This command is run by the **human**, not the agent

## Steps

### 1–3. Validate, Decide, Record — run the deterministic core

Run:

```
bash scripts/review-decide.sh <project-dir> <approve|reject|retry>
```

The script owns every state transition that must not depend on
prompt-following (#233):

- **Breaker file present** → `breaker_type` is read from it.
- **Breaker file missing** → the context is RECONSTRUCTED, bound to THIS
  feature via `.cct/review/state.json`'s `feature_id` (never a scan of
  other features' ledgers): the newest unresolved `review_breaker`
  escalation under `.cct/auto-build/<feature_id>/escalations/` supplies it
  (`breaker_type: runner_crash_legacy` for `review runner exited <n>`
  details, `reconstructed` otherwise), and `reconstructed_from` provenance
  is recorded in `decision.json` — the driver validates it against the
  escalation it resolves on `--resume`. A corrupt record, a missing
  `feature_id`, or no unresolved `review_breaker` escalation refuses with
  the precise reason; "Nothing to decide" is only said when no unresolved
  `review_breaker` escalation exists for this feature.
- **retry** → the script bumps `attempt` and resets `loop_start`
  (mandatory in reconstruction mode too — a stale `loop_start` trips the
  review loop clock before the next reviewer runs).
- `breaker-tripped.json` is removed after the decision is recorded.

Display the script's output to the user. If it refuses, relay its message
and stop.

### 4. Execute Decision Path

**approve**:
- Write `.cct/review/loop-summary.json` with `bypass: true`, the breaker type, and all unresolved findings from `state.json`.
- Write the collaboration artifact to `specs/<feature-id>/collaboration/build-review.md` with `bypass: true` in frontmatter.
- Inform the user: "Review bypassed. Proceeding to `/phase-complete`. CI will flag the bypass."
- Proceed to `/phase-complete`.

**reject**:
- Write `.cct/review/loop-summary.json` with `verdict: "REJECTED"` and all context.
- Inform the user: "Review rejected. No merge. Session can be ended."
- Do not proceed to `/phase-complete`.

**retry**:
- The attempt bump and `loop_start` reset were already applied by
  `scripts/review-decide.sh` in step 1–3 — do NOT apply them again.
- Round numbering continues monotonically — if the breaker fired after round 5, the next round is 6, not 1.
- Inform the user: "Breaker reset. Run `/review-submit` to continue the review loop."
- The agent should then run `/review-submit` to start the next round.
- For an auto-build park: rerun `scripts/auto-build-loop.sh <feature-id> --resume`
  instead — the driver consumes the decision and re-enters the review loop itself.
