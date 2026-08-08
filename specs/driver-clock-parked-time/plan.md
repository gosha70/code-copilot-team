---
spec_mode: none
feature_id: driver-clock-parked-time
risk_category: bugfix
justification: |
  Non-security bug fix (#210): the sibling of #205. Move the driver's
  wall-clock reset into the common resume path so both guards agree. One
  statement plus a regression; no new surface.
status: approved
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/210
  origin_claim: |
    Bug #210: "Driver wall-clock cap still bills parked time (#205 fixed
    only the review-loop clock)". `totals.started_epoch` is set once at run
    init and reset ONLY on the cap_exceeded resume path, so resuming from
    review_breaker / git_anomaly / provider_unavailable / test_failure /
    origin_gate keeps the original start time and bills the human's
    turnaround against the 4h cap. Observed: a run killed at "17886s of
    14400s" having done ~25 minutes of actual work. Proposed fix: reset
    started_epoch on every successful resume, matching the review loop's
    post-#207 behaviour so both guards agree.
---

# Plan: the driver's clock must not bill parked time either (#210)

The reset moves into the common success path of `resume_parked()` — the
same place #205 put the review-loop reset — so both wall-clock guards
restart together and cannot drift apart again. The `cap_exceeded` arm keeps
its own reset (it also re-reads caps); the two now agree rather than
conflict.

While here, a comment written in #205 claimed the driver's guard "already
restarts on resume". It did not — that was exactly this bug — and the
claim is corrected in place rather than left to mislead the next reader.

## Semantics chosen

Per-attempt, not cumulative: each successful resume restarts the budget.
The issue offers accumulating active time as an alternative; that is a
different product decision (a true cumulative work-time budget) and would
also require persisting elapsed at every park. The per-attempt reading is
what the review loop already does post-#207, and matching the sibling guard
was the issue's own stated requirement.

## Test note

The first version of the regression parked a single-phase run and passed
against master — because the resumed run had no session left to run, so
`check_caps()` was never called. It now uses two phases, so the resumed run
still has a build session; against master it dies with
`cap_exceeded — wall-clock cap`, which is the reported failure.
