# Tasks: verification contract, increment C1 (#222)

Each task is independently reviewable and leaves the suites green.

## T1 — Config surface (FR-1, FR-2, FR-8)
- `verification` block in `shared/schemas/automation.schema.json` (typed,
  surgical edit — no reformat).
- `validate-automation-config.sh`: per-key checks, named failure messages,
  unknown-key rejection, `conformance.required` accepted-but-inadmissible.
- Template `automation-template.json` gains a commented example.
- Tests in `test-automation-config.sh`.

## T2 — Coverage parsing (FR-6)
- `scripts/lib/coverage-parse.sh`: `istanbul` + `lcov` → `{line_pct,
  branch_pct}`; `cobertura`/`jacoco` refuse with "not implemented in C1".
- Fixtures for both supported formats, incl. a malformed artifact.
- Its own test file; wired into sync-check.

## T3 — Presets (FR-5)
- `shared/templates/<type>/verification-preset.json` for the templates that
  ship a test story; resolution order preset → `automation.json` override.
- Assert no numeric floor literal exists in any script.

## T4 — Admission checks (FR-3, FR-4 capture, FR-7, FR-10)
- Greenfield: no artifact required; brownfield: capture baseline into the
  ledger beside the config snapshot.
- UI-in-scope + missing toolchain ⇒ refuse (unattended only).
- Account for the `test.command` invocation.
- Tests in `test-verification-spec.sh`.

## T5 — Driver enforcement (FR-3, FR-4 enforcement)
- Coverage gate at `floor_enforced_at` (`landing` default, `phase` option).
- Regression comparison against the admitted baseline, not a live re-read.
- Failure parks (attended) / terminates (unattended) with a reason naming
  the number and the floor.
- Tests in `test-auto-build-loop.sh`.

## T6 — Worktree prune (FR-9)
- `git worktree prune` at preflight; test that a stale registration is
  reclaimed.

## T7 — Docs + gates
- README section, CHANGELOG, schema description, count pins.
- `validate-spec.sh`, origin alignment, full suite sweep.
- Each SC's regression verified to fail against the pre-change code.
