# Spec: review-loop wall-clock and breaker naming (#205)

## Requirements

- **FR-1**: A successful resume MUST restart the review loop's wall-clock,
  so time spent parked awaiting human action is not counted against it.

- **FR-2**: The reset MUST happen only on a genuine resume. Paths that
  refuse to resume MUST NOT touch the clock.

- **FR-3**: The park message MUST name the breaker for runner-produced
  breaker files (`breaker`) as well as driver-produced ones
  (`breaker_type`), including files already written to disk.

- **FR-4**: The review loop wall-clock MUST be configurable from
  `automation.json` as `review.loop_timeout_sec`, default 900. An explicit
  `CCT_REVIEW_TIMEOUT_SEC` still wins.

- **FR-5**: A `loop_timeout_sec` that is not a positive integer MUST fall
  back to the default with a warning, never be evaluated as 0.

## Constraints — what NOT to build

- Do NOT reset the clock inside the runner. The runner cannot tell a
  resume from an ordinary round; the driver owns resume semantics.
- Do NOT wire `review.round_timeout_sec`. It is inert today, it is a
  different knob, and silently giving it behaviour would change existing
  runs. Document the distinction instead.
- Do NOT relax the breaker itself. The wall-clock still bounds a running
  loop; this only stops it billing time the run was not running.
