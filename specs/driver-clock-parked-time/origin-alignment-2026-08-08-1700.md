# Origin Alignment Check — driver-clock-parked-time

Date: 2026-08-08 17:00
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/210 (line
  references, the real-run evidence "17886s of 14400s", the proposed fix,
  and four acceptance criteria).
- The user's instruction: "start …/issues/210".
- #205 / PR #207, the sibling fix this one is measured against.

## Origin claim (verbatim)

> #205 / PR #207 fixed the **review-loop** clock so it no longer bills
> parked time. The **driver's own** wall-clock cap (`caps.wall_clock_sec`)
> still has the same defect … Resuming from any *other* park reason keeps
> the original start time, so every minute a human spent resolving the park
> is billed against the 4h cap.

## Acceptance criteria — status

- Resuming from review_breaker / git_anomaly / provider_unavailable /
  test_failure / origin_gate does not bill parked time — **met**; the reset
  is in the common resume path, and the regression asserts the park it
  resumes from is `provider_unavailable`, so the cap_exceeded arm cannot
  mask the fix.
- `cap_exceeded` resume behaviour unchanged — **met**; that arm keeps its
  own reset and its caps re-read.
- Driver and review-loop semantics documented as consistent — **met**, in
  the code comment and plan.
- Regression: park → advance the clock past `wall_clock_sec` → resume ⇒
  phase proceeds, no `cap_exceeded` — **met**, and verified to fail against
  master.

## Mismatches

- The issue offers a second semantic (accumulate active time across
  attempts). I chose the per-attempt reset because it matches the review
  loop post-#207, which the issue itself sets as the bar. A cumulative
  work-time budget is a different product decision and would need elapsed
  time persisted at every park — flagged, not silently chosen.
- **Test honesty:** the first version of the regression passed against
  master because a single-phase resume had no session left, so
  `check_caps()` never ran. It was changed to two phases and re-verified to
  fail against master before being kept.

## Verdict

Verdict: aligned
Confidence: high
