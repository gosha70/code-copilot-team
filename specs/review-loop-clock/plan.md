---
spec_mode: lightweight
feature_id: review-loop-clock
risk_category: feature
justification: |
  Bug fix (#205) with three defects, one of which changes breaker
  behaviour on resume and one of which adds an automation.json key.
  Escalated from `none` per the spec-workflow "when in doubt" rule
  because it alters when a circuit breaker fires.
status: approved
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/205
  origin_claim: |
    Bug #205: "Review-loop breaker counts parked/human time — resume after
    any >15min park trips it instantly (+ breaker name reads 'unknown',
    timeout not configurable)". Three defects hit in a single real run:
    (1) loop_start is never reset on resume, so the 900s review-loop
    wall-clock counts time the run sat PARKED waiting for a human —
    any park taking more than 15 minutes trips the breaker instantly on
    resume, before a single review round runs; (2) the breaker name always
    reads 'unknown' for runner-produced breakers because the runner writes
    `breaker` and the driver reads `breaker_type`; (3) the 900s loop
    timeout is not configurable from automation.json, while
    review.round_timeout_sec sitting there misleadingly suggests review
    timeouts are configured there.
---

# Plan: the review clock must not bill human thinking time (#205)

## D1 — `loop_start` counted parked time (the blocking one)

`loop_start` was set once when review state was initialised and carried
verbatim through every round; nothing reset it when a run parked and was
later resumed. Parking exists *to invite human intervention*, and every
park reason — `provider_unavailable`, `test_failure`, `origin_gate`,
`git_anomaly`, `cap_exceeded` — needs an action that realistically takes
longer than 15 minutes. So resuming from any of them landed straight in a
breaker park, and the human had to run `/review-decide retry` purely to
clear a timer that had measured their own thinking time.

Fixed by restarting the clock on a successful resume, at the end of
`resume_parked()`. This mirrors the driver's own guard, which already
restarts on resume (the `cap_exceeded` arm resets `totals.started_epoch`).
Every arm that reaches the reset has resolved its escalation, and
`refuse_resume` exits, so falling through means the resume genuinely
succeeded.

The regression is the reported scenario: park, backdate the clock an hour,
resume. Against the previous driver it parks (exit 4) with
`wall-clock timeout`; now it completes.

## D2 — every runner breaker reported as `unknown`

Two producers of `breaker-tripped.json` with two key names: the runner
writes `breaker`, the driver writes `breaker_type`, and the driver read
only the latter. The park told the user a breaker fired but not which one,
while the file plainly said `"timeout"`. The driver now reads
`.breaker_type // .breaker // "unknown"`, which also fixes files already
on disk. Nothing else in the repo reads either key (verified by grep).

## D3 — the loop timeout was env-only

`review.loop_timeout_sec` is now read from `automation.json` (default 900,
the runner's historical value) and passed through as
`CCT_REVIEW_TIMEOUT_SEC`, with an explicit env override still winning. A
non-numeric value falls back to 900 with a warning rather than being
evaluated as `0` by the runner's arithmetic comparison, which would trip
the breaker on the first round of every run.

`review.round_timeout_sec` is a DIFFERENT knob and is documented as such
in the schema description. Note it is currently inert — nothing reads it;
per-invocation timeouts come from `timeout_sec` in `providers.toml`. That
is pre-existing and left alone here rather than silently rewired.
