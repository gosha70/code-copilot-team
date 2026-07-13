# Spec: Review-engine generalization + collaboration CI tightening

Increment A (#68) of the auto-build-loop series. See plan.md and
specs/auto-build-loop/design.md for the series design.

## Requirements

- FR-1: `scripts/review-round-runner.sh` MUST read the review diff base ref
  from `CCT_REVIEW_BASE_REF`, defaulting to `HEAD~1`. All three uses of the
  base ref (diff stat, diff body, truncation check) MUST honor the variable.
- FR-2: `scripts/review-round-runner.sh` MUST read the diff line cap from
  `CCT_REVIEW_DIFF_MAX_LINES`, defaulting to `500`. Both the `head` cap and
  the truncation check (and the truncation notice text) MUST honor the
  variable.
- FR-3: With neither variable set, the generated review request MUST be
  byte-identical in behavior to the current implementation (diff of `HEAD~1`,
  truncated at 500 lines).
- FR-4: `scripts/validate-collaboration.sh` MUST fail a `build-review.md`
  whose `blocking_findings_open` is non-zero unless the artifact carries an
  approved bypass (`bypass: true` with a logged `breaker_type`), regardless of
  the `verdict` value.
- FR-5: `.cct/` MUST be gitignored at the repository root.
- FR-6: Existing `tests/test-review-loop.sh` assertions MUST pass unchanged
  under default environment; new assertions MUST cover FR-1, FR-2, and FR-4;
  `tests/test-counts.env` expected counts MUST be updated accordingly.

## Constraints

- Bash 3.2 compatibility (repo convention; macOS system bash).
- No behavior change with default environment (FR-3) — the review-loop
  contract consumed by /review-submit and the peer-review stop hook is
  untouched.
- No changes to origin-confirmation semantics or any other script.
- One issue per PR: this bundle covers exactly #68.
