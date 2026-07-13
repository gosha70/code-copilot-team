---
spec_mode: lightweight
feature_id: auto-build-loop-review-engine
risk_category: low
justification: |
  Small, behavior-preserving parameterization of two existing scripts plus one
  .gitignore line. No new subsystems, no new dependencies, defaults preserve
  exact current behavior. First (enabler) increment of the auto-build-loop
  feature series (#68 -> #71); full design in
  specs/auto-build-loop/design.md.
status: approved
date: 2026-07-13
issue: 68
origin:
  issue: gosha70/code-copilot-team#68
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/68
  origin_claim: |
    Issue #68 (increment A of the auto-build-loop series, planned and approved
    in the 2026-07-13 planning session): (1) parameterize the review diff in
    scripts/review-round-runner.sh — CCT_REVIEW_BASE_REF (default HEAD~1) for
    the three HEAD~1 literals and CCT_REVIEW_DIFF_MAX_LINES (default 500) for
    the diff-truncation literals; (2) tighten scripts/validate-collaboration.sh
    so blocking_findings_open > 0 fails regardless of verdict unless an
    approved bypass is present; (3) gitignore .cct/. Defaults preserve current
    behavior; existing test-review-loop.sh assertions must keep passing; new
    assertions cover the knobs and the forged-PASS case.
---

# Plan: Review-engine generalization + collaboration CI tightening

Enabler increment for the autonomous build driver (#69): the driver reviews
multi-commit phase diffs (base-of-phase..HEAD), not `HEAD~1`, and must be able
to raise the diff cap for whole-phase reviews. The CI tightening closes the
forged-artifact gap independently of the driver.

## Changes

1. `scripts/review-round-runner.sh`
   - Config block: `BASE_REF="${CCT_REVIEW_BASE_REF:-HEAD~1}"` and
     `DIFF_MAX_LINES="${CCT_REVIEW_DIFF_MAX_LINES:-500}"`.
   - Replace the three `HEAD~1` literals (diff stat / diff body / truncation
     check, currently lines 339, 344, 347) with `"$BASE_REF"` and the `500`
     literals (and the "truncated at 500 lines" message) with `"$DIFF_MAX_LINES"`.
2. `scripts/validate-collaboration.sh`
   - Blocking-findings check (currently line 99): fail when
     `blocking_findings_open` is non-zero and `bypass != true`, regardless of
     verdict. Today a hand-edited `verdict: PASS` + `blocking_findings_open: 3`
     passes CI; the runner itself never emits that combination (it downgrades
     PASS at line 543), so this only catches forged/hand-edited artifacts.
3. `.gitignore`: add `.cct/` (machine-local collaboration/automation state;
   currently only tolerated as untracked by the runner's dirty-check).

## Tests

- `tests/test-review-loop.sh`: all existing assertions pass unchanged with
  default env; add assertions that (a) `CCT_REVIEW_BASE_REF` changes the diff
  range in the generated review request, (b) `CCT_REVIEW_DIFF_MAX_LINES`
  changes the truncation threshold, (c) a forged PASS artifact with open
  blocking findings fails `validate-collaboration.sh`.
- Bump the affected expected counts in `tests/test-counts.env`.
