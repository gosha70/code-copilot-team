# Origin Alignment Check — driver-clock-parked-time

Date: 2026-08-08 17:45
Trigger: plan.md revised after the user's P1 on PR #218; the previous
record (`origin-alignment-2026-08-08-1700.md`) is stale.

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/210.
- The user's P1 on PR #218: "Milestone resumes still bill human sign-off
  time. The reset is only inside `resume_parked()` … The `milestone-paused`
  branch resumes without resetting `totals.started_epoch` … Factor the
  clock reset into a helper used by both successful resume paths, and add a
  three-phase milestone regression. The current milestone test ends after
  phase 2, so no capped session remains to expose this."

## Working claim

`reset_run_clocks()` is the single implementation, called from
`resume_parked()` and from the `milestone-paused` arm after sign-off
succeeds. A three-phase regression pauses at a milestone, backdates the
clock six hours past the fixture's cap, signs off, and asserts the run
completes with phase 3 actually executing.

## Mismatches

- none against the finding. Both remedies the user asked for were taken
  verbatim: the helper, and the three-phase regression.

Verified to fail against `4d569a7`: `milestone resume completes despite a
six-hour sign-off wait (expected exit 0, got 4)` and `the third phase
actually ran (expected '1', got '0')` — the reported hole, reproduced.

This is the second time this fix shipped with a resume path uncovered
(#210 itself was #205's uncovered sibling). The helper exists so the answer
to "which resume paths reset the clock?" is one grep, not an audit.

## Verdict

Verdict: aligned
Confidence: high
