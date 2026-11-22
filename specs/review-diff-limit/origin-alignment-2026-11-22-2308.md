# Origin Alignment Check — review-diff-limit

Date: 2026-11-22 23:08
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/504. In the
  wiki-studio-patterns-54 run (2026-11-19), phase 2 had a 4,041-line diff;
  the reviewer, shown the first 500 lines, answered INCONCLUSIVE and the
  run parked. A rerun with `CCT_REVIEW_DIFF_MAX_LINES=6000` passed. The
  issue offers three fixes and asks that, whichever is chosen, the park
  message say how many lines the diff had against the limit.
- The owner's instruction of 2026-11-22, quoted in `plan.md` as the
  origin claim: the key, frozen into the config snapshot; precedence
  variable, then config, then 500; the message; the default kept at 500;
  check the spec-first rules.

## Acceptance criteria — status

- `review.diff_max_lines` in `automation.json` sets the limit — **met**.
  The schema, the validator and the template carry it, and the driver
  passes it to the gating round and the advisory pass: the captured
  requests were cut at 3 lines (gating) and at 2 (advisory).
- Frozen into the config snapshot, so it survives `--resume` — **met**. A
  run started with 3 was resumed after the live config was changed to 4;
  the rerun review was cut at 3, and the resume note reads "diff limit: 3
  lines, from review.diff_max_lines in automation.json".
- Precedence: the variable, then the config value, then 500 — **met**. The
  variable (2) beat the config value (3) at launch and (5) on resume; an
  invalid variable is ignored with a warning and the config value applies;
  with neither, the limit is 500.
- The park message gives the diff's line count against the effective limit
  and where it came from — **met**: "The diff had 8 lines against a limit
  of 3 (from review.diff_max_lines in automation.json), so the reviewer saw
  only the first 3."
- The default stays 500 — **met**. The runner's default is unchanged, and
  the driver falls back to 500.
- A short plan under the spec-first rules — **met**. `plan.md` with
  `spec_mode: none`: a non-security bug fix, for which the rules require a
  plan and refuse a `spec.md`, as #227's `review-round-ceiling` did for
  `review.max_rounds`.

Against the unchanged driver, 10 of the 17 new checks fail. The seven that
hold there are exit codes and the two cuts made by the variable alone,
which already reached the runner.

## Mismatches

- Of the issue's three options the owner chose the config key and kept the
  default. A larger default and a review that summarises or skips large
  data files are not built.
- The decisions taken beyond the owner's message are listed in `plan.md`:
  the advisory pass, invalid values, how the count is taken, and the remedy
  named for a parked run.

## Verdict

Verdict: aligned
Confidence: high
