# Spec: cost cap visibility (#201)

## Requirements

- **FR-1**: The README MUST document `caps.cost_usd`: the default, where it
  lives, the `cap_exceeded` park, and the `--resume` semantics.

- **FR-2**: Each phase gate MUST print the running spend against the cap.
  When any part of the total is a conservative estimate, the line MUST say
  so — an estimate must never read as measured spend.

- **FR-3**: Attended profiles MUST re-read `caps.cost_usd` from the live
  config at each phase gate, so a raise applies without first parking. The
  change MUST update the frozen snapshot, be announced on stdout, and be
  journalled.

- **FR-4**: A non-positive or non-numeric live cap MUST be ignored, leaving
  the frozen value intact.

- **FR-5**: The `unattended` profile MUST NOT re-read caps mid-run; it stays
  bound to the config it was admitted against.

- **FR-6**: The docs MUST state that the cost cap was inert before the
  #197/#198 result-parsing fix, so users on older versions do not assume
  they were protected.

## Constraints — what NOT to build

- Do NOT widen the live re-read beyond `caps.cost_usd`. Freezing config at
  launch is a deliberate property (#193); this is a scoped exception for the
  one value a human adjusts while watching a run.
- Do NOT re-read mid-phase. A session must not see its budget change under
  it; the phase gate is the only safe point.
- Do NOT add a pre-run cost estimate here. It needs cross-run history and an
  estimation model — separate work.
- Do NOT change enforcement. `check_caps()` and the `cap_exceeded` park are
  correct and stay as they are.
