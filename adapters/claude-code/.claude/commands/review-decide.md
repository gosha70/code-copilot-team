Resolve a circuit breaker in the review loop. Accepts exactly one argument: approve, reject, or retry.

## Usage

```
/review-decide approve
/review-decide reject
/review-decide retry
```

## Prerequisites

- A live breaker: either `.cct/review/breaker-tripped.json` exists, **or** an
  unresolved `review_breaker` escalation exists in
  `.cct/auto-build/*/escalations/esc-*.json` (a crash can park the run
  without ever writing the breaker file — #233)
- This command is run by the **human**, not the agent

## Steps

### 1. Validate Breaker State

Check that `.cct/review/breaker-tripped.json` exists:
- If present, read and display the breaker context (type, rounds completed, unresolved findings).
- If missing, **do not stop yet** — scan `.cct/auto-build/*/escalations/esc-*.json`
  for the newest record with `reason == "review_breaker"` and `resolved == false`:
  - **Found** → reconstruct the breaker context from the escalation (#233):
    `breaker_type` is `"runner_crash_legacy"` when the escalation's `detail`
    matches `review runner exited <n>`, otherwise `"reconstructed"`; rounds
    and findings come from `.cct/review/state.json` and
    `findings-round-*.json` where present. Display the reconstructed context,
    warn that a crash park's review state may be inconsistent (findings can
    be newer than `state.json`), and proceed to step 2. Record the provenance
    in `decision.json` (step 3).
  - **Not found** → inform the user precisely: "No active circuit breaker:
    `.cct/review/breaker-tripped.json` does not exist and no unresolved
    `review_breaker` escalation was found under `.cct/auto-build/`. Nothing
    to decide." Never say "nothing to decide" while an unresolved
    `review_breaker` escalation exists.

### 2. Parse Decision

The argument must be exactly one of: `approve`, `reject`, or `retry`.
- If missing or invalid, show usage and stop.

### 3. Write Decision

Write `.cct/review/decision.json`:

```json
{
  "decision": "<approve|reject|retry>",
  "timestamp": "<ISO-8601>",
  "breaker_type": "<from breaker-tripped.json>"
}
```

When the context was **reconstructed** (no `breaker-tripped.json`), add the
provenance so the audit trail says where the type came from:

```json
{
  "decision": "<approve|reject|retry>",
  "timestamp": "<ISO-8601>",
  "breaker_type": "<runner_crash_legacy|reconstructed>",
  "reconstructed_from": "<path of the unresolved escalation record>"
}
```

Remove `.cct/review/breaker-tripped.json` after writing the decision (skip
if it never existed).

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
- Read `state.json` and increment the `attempt` counter.
- Reset breaker state: set `loop_start` to current time (resets wall-clock timer).
- These two steps are **mandatory in reconstruction mode too** (#233's
  second-order trap): a crash park can sit for hours, and a recovery that
  only writes `decision.json` trips the review loop clock before the next
  reviewer even runs.
- Round numbering continues monotonically — if the breaker fired after round 5, the next round is 6, not 1.
- Inform the user: "Breaker reset. Run `/review-submit` to continue the review loop."
- The agent should then run `/review-submit` to start the next round.
- For an auto-build park: rerun `scripts/auto-build-loop.sh <feature-id> --resume`
  instead — the driver consumes the decision and re-enters the review loop itself.
