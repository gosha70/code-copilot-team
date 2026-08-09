# Tasks: verification contract, increment C1 (#222) — rev 2

Each task is independently reviewable and leaves the suites green.

## T1 — Config surface (FR-1, FR-1a, FR-2)
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

## T4 — Admission-result channel (FR-7, FR-7a, FR-9)
- Admission writes `{baseline, test_command}` to a temp file before the
  throwaway worktree is cleaned; returns its path.
- Driver imports into the ledger only after admission succeeds and the
  ledger exists, then removes it.
- Test the refusal case: no ledger, no leftover file.

## T5 — Admission checks (FR-3, FR-4 capture)
- Greenfield: no artifact required. Brownfield: run coverage in the
  throwaway worktree and capture via T4.
- Tests in `test-verification-spec.sh`.

## T6 — Driver enforcement (FR-3, FR-4 enforcement)
- Coverage gate at `floor_enforced_at`; regression against the ADMITTED
  baseline; failure parks (attended) / terminates (unattended) with a
  reason naming the measured number and the floor.
- Tests in `test-auto-build-loop.sh`.

## T7 — Worktree prune (FR-8)
- `git worktree prune` at preflight; test a stale registration is reclaimed.

## T8 — Docs + gates
- README, CHANGELOG, schema description, count pins.
- Record in #222 that `skip_is_failure` is deferred to C3 and the issue
  stays open for it.
- validate-spec, origin alignment, full sweep; every SC regression verified
  to fail against the pre-change code.
