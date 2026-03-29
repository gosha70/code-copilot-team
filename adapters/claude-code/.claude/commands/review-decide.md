Resolve a circuit breaker in the review loop. Accepts exactly one argument: approve, reject, or retry.

## Usage

```
/review-decide approve
/review-decide reject
/review-decide retry
```

## Prerequisites

- `.cct/review/breaker-tripped.json` must exist (a circuit breaker has fired)
- This command is run by the **human**, not the agent

## Steps

### 1. Validate Breaker State

Check that `.cct/review/breaker-tripped.json` exists:
- If missing, inform the user: "No active circuit breaker. Nothing to decide."
- If present, read and display the breaker context (type, rounds completed, unresolved findings).

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

Remove `.cct/review/breaker-tripped.json` after writing the decision.

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
- Round numbering continues monotonically — if the breaker fired after round 5, the next round is 6, not 1.
- Inform the user: "Breaker reset. Run `/review-submit` to continue the review loop."
- The agent should then run `/review-submit` to start the next round.
