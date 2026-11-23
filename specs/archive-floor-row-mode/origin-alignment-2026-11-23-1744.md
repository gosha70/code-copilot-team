# Origin Alignment Check — archive-floor-row-mode

Date: 2026-11-23 17:44
Trigger: a wording correction to `plan.md` D1, asked for by the owner in
the approval of PR #516 (merged at `6de5f3e`).

## Origin sources read

- The owner's note: "plan D1 in specs/archive-floor-row-mode/plan.md still
  says a row with no recorded mode takes the session's; since 6de5f3e it
  counts as none. Fix that sentence there."

## Acceptance criteria — status

- D1 states the behaviour the code has had since `6de5f3e` — **met**. A row
  with no, an empty, or an unknown recorded mode counts as `none` and fails
  closed. The code and the tests (`test_redaction`,
  `test_an_archived_row_with_no_or_an_unknown_mode_fails_closed`) are
  unchanged.
- The rest of the 15:47 record stands; nothing else in the plan changed.

## Mismatches

None.

## Verdict

Verdict: aligned
Confidence: high
