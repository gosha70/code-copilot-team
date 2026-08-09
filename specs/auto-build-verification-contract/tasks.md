# Tasks: verification contract, increment C1 (#222) — rev 5

Each task is independently reviewable and leaves the suites green.

## T1 — Config surface (FR-1, FR-1a, FR-2, FR-4b)
- Every FR-4b rule: required keys, 0-100 ranges, at-least-one-floor,
  `max_regression_pct` rejected under `baseline: none`, `artifact`
  containment (no absolute, no `..`), parser enum.
- `verification.coverage` in `shared/schemas/automation.schema.json`
  (surgical edit, no reformat).
- `validate-automation-config.sh`: per-key checks with named messages;
  unknown keys rejected; `test`/`app`/`visual`/`conformance` rejected as
  "not supported in C1".
- Tests in `test-automation-config.sh`, incl. the no-block byte-identical
  case.

## T2 — Coverage parsing (FR-6)
- `scripts/lib/coverage-parse.sh`: istanbul + lcov -> `{line_pct,
  branch_pct}`; cobertura/jacoco refuse by name.
- Fixtures per format plus a malformed artifact.
- Own test file, wired into sync-check.

## T3 — Presets (FR-5)
- `shared/templates/<preset>/verification-preset.json` for templates with a
  test story; explicit `preset` key resolution; fail closed when absent or
  unknown unless every floor is supplied.
- Assert no floor literal in any script.

## T4 — Admission-result channel + lifecycle (matrix is normative)
- `shared/schemas/admission-result.schema.json`: closed, versioned, `mode`
  discriminator; `resume` forbids `coverage_contract`.
- Contract INITIALISATION as a preflight step keyed on the block, shared by
  both profiles; admission bar stays unattended-only.
- No-block resume takes the legacy path (regression: it must not fail).

## T4b — original channel items (FR-7, FR-7a, FR-7b, FR-7c, FR-9, FR-9a, FR-9b)
- Implement the two sequences literally (fresh / resume) from plan.md.
- Resume: load + schema-validate the existing frozen contract; no
  recapture; fail closed when missing/corrupt.
- `reset_run_clocks()` gains an explicit timestamp parameter; existing
  callers pass `now`; the resume path passes ATTEMPT_START.
- Pending-event buffer flushed after ledger init; stderr on refusal.
- DRIVER creates the path, passes `--result-file`, schema-validates the
  return, imports atomically, removes it on every exit (trap). No path
  scraped from diagnostic output.
- Admission writes the FROZEN CONTRACT (FR-4a) plus `test_command`
  accounting before the throwaway worktree is cleaned.
- Pre-admission timestamp initialises `totals.started_epoch` (FR-9), with a
  test that the cap actually includes admission time.
- Test the refusal case: no ledger, no leftover file.

## T5 — Admission checks (FR-3, FR-4 capture)
- Greenfield: no artifact required. Brownfield: run coverage in the
  throwaway worktree and capture via T4.
- Tests in `test-verification-spec.sh`.

## T6 — Driver enforcement (FR-3, FR-4, FR-4a, FR-4b arithmetic)
- Coverage gate at `floor_enforced_at`, reading ONLY the frozen contract —
  with a test that editing the preset file after admission changes nothing.
- Regression in percentage POINTS against the frozen baseline.
- A floor whose metric the artifact lacks fails closed.
- Failure parks (attended) / terminates (unattended) naming the measured
  number and the floor.
- Tests in `test-auto-build-loop.sh`.

## T7 — Worktree prune (FR-8)
- Prune on the unattended admission path only, before admission creates its
  worktree; non-fatal and journalled on failure.
- Tests: stale registration reclaimed; attended run does not prune; a
  failing prune does not fail the run.

## T8 — Docs + gates
- README, CHANGELOG, schema description, count pins.
- Record in #222 that `skip_is_failure` is deferred to C3 and the issue
  stays open for it.
- validate-spec, origin alignment, full sweep; every SC regression verified
  to fail against the pre-change code.
