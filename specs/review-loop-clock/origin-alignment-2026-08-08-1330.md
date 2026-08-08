# Origin Alignment Check — review-loop-clock

Date: 2026-08-08 13:30
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/205
  (`gh issue view 205` — three defects, each with line references, the
  observed console output, the `state.json`/`breaker-tripped.json`
  evidence, and explicit acceptance criteria).
- The user's instruction: "do #205 next".

## Origin claim (verbatim)

> 1. **`loop_start` is never reset on resume**, so the 900s review-loop
>    wall-clock counts the time the run sat **parked waiting for a
>    human**. … any park that takes more than 15 minutes to resolve trips
>    the breaker **instantly** on resume — before a single review round
>    runs.
> 2. **Breaker name always reads `unknown` for runner-produced breakers**
>    — the runner writes `breaker`, the driver reads `breaker_type`.
> 3. **The 900s loop timeout is not configurable from `automation.json`**
>    — only via the `CCT_REVIEW_TIMEOUT_SEC` env var.

## Working claim

`resume_parked()` restarts the review clock on a successful resume; the
driver reads `.breaker_type // .breaker // "unknown"`; and
`review.loop_timeout_sec` (default 900) is read from `automation.json`
and passed to the runner, with a non-numeric value falling back rather
than becoming 0.

## Acceptance criteria (from the issue) — status

- Resuming a parked run does not trip the review wall-clock breaker on
  parked time — **met**, pinned by a regression that parks, backdates the
  clock an hour, and resumes: exit 4 before, exit 0 now.
- The park message names the actual breaker — **met**, both key shapes
  asserted.
- The loop wall-clock is configurable from `automation.json` and its
  relationship to `round_timeout_sec` is documented — **met** (schema
  description plus plan.md).
- Regression tests (a) and (b) — **met**, plus a third for the
  non-numeric fallback.

## Mismatches

- **`round_timeout_sec` was left inert.** The issue notes it
  "misleadingly suggests review timeouts are configured there". I
  documented the distinction rather than wiring it: it is a different
  knob, nothing reads it today, and giving it behaviour would silently
  change the timeout of existing runs that already carry the key from the
  template. Flagging rather than hiding — if the intent was for it to
  bound a single round, that is a behaviour change worth its own issue.
- Chose the first of the issue's three proposed D1 fixes ("reset
  loop_start on resume"), which it calls out as matching existing
  precedent.

## Verdict

Verdict: aligned
Confidence: high
