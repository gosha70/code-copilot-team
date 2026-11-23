---
spec_mode: none
feature_id: review-diff-limit
risk_category: bug
justification: |
  Non-security bug fix (#504): a data-heavy phase parks as
  review_inconclusive because the review diff limit can be raised only
  with an environment variable, which a resumed run does not carry. The
  fix adds one optional key, review.diff_max_lines, beside max_rounds and
  loop_timeout_sec and wired the same way (#227, #205). The default and
  every existing config behave as before.
status: approved
date: 2026-11-22
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/504
  origin_claim: |
    The owner, 2026-11-22: "Take #504 next. Add review.diff_max_lines to
    automation.json, frozen into the config snapshot so it survives
    --resume. Precedence: CCT_REVIEW_DIFF_MAX_LINES, then the config value,
    then the 500 default. The inconclusive park message should give the
    diff's line count against the effective limit and where the limit came
    from. Keep the default at 500. Check whether the new config key needs a
    short plan under the repo's spec-first rules."
---

# Plan: the review diff limit is run configuration (#504)

**D1. The key.** `review.diff_max_lines`, an integer of at least 1, joins
`max_rounds` and `loop_timeout_sec` in the schema, the validator and the
template. The driver reads it in `load_config` from the config snapshot,
which `init_ledger` freezes at launch and `--resume` binds to, so a resumed
run keeps it without the variable. It is not refreshed from the live config
on resume, as caps, `pr` and `merge` are.

**D2. Precedence.** `CCT_REVIEW_DIFF_MAX_LINES`, then
`review.diff_max_lines`, then 500. The driver passes the effective limit to
each runner call it makes over the phase diff.

**D3. The park message.** `review_inconclusive` gives the diff's line
count against the effective limit and where the limit came from: the
default, `review.diff_max_lines` in `automation.json`, or
`CCT_REVIEW_DIFF_MAX_LINES`. The message on `--resume` names the limit then
in effect and its source.

**Default.** 500, unchanged.

## Decided here, beyond the owner's message

- The advisory pass gets the same limit as the gating round. It reviews the
  same diff, and an environment variable already reaches both.
- A value that is not a positive integer is ignored with a warning, from
  either place. The validator rejects a numeric non-integer at admission
  and leaves other types to the driver, its policy for `max_rounds`.
- The count is `git diff <phase base> | wc -l`, the measure the runner
  truncates by. The message says whether the reviewer saw all of the diff.
- For a parked run the message points at `CCT_REVIEW_DIFF_MAX_LINES` on the
  `--resume` command, because the run keeps the `review.diff_max_lines` it
  started with.

## Not changed

- `scripts/review-round-runner.sh` still reads only
  `CCT_REVIEW_DIFF_MAX_LINES` (default 500), so standalone use is the same.
- The issue's other options: a larger default (the owner keeps 500), and a
  review that summarises or skips large data files instead of cutting the
  diff at a line count.

## Files

- `shared/schemas/automation.schema.json`, `scripts/validate-automation-config.sh`
- `scripts/auto-build-loop.sh`
- `shared/templates/sdd/automation-template.json` and its generated plugin copy
- `docs/auto-build.md`, `docs/auto-code-review-setup.md`,
  `docs/configuration-reference.md` (generated), `CHANGELOG.md`
- `tests/test-auto-build-loop.sh`, `tests/test-automation-config.sh`,
  `tests/test-counts.env`, `docs/repo-structure.md`

## Verification

The new driver cases run against the unchanged driver first and must fail
there. Then the whole auto-build and automation-config suites,
`validate-spec.sh` and `check-origin-alignment.sh` for this feature, the
generator drift check, and `check-doc-accuracy.sh`.
