# Spec: verification contract, increment C1 (#222)

## User Scenarios

**US1 — Greenfield product build.** An operator points an unattended run at
an empty repository with a `verification` block declaring
`coverage.baseline: none`, `min_line_pct: 80`. Admission does not demand a
coverage artifact that cannot exist yet. The run builds, and at the landing
gate coverage below 80% fails the run instead of landing it.

**US2 — Brownfield feature.** The same block with `baseline: admission`.
Admission captures the base ref's coverage. A phase that lands code
reducing coverage fails on regression even if the absolute floor is still
met; code below the floor fails on the floor even with no regression.

**US3 — UI work on a host without Playwright.** A contract with UI in scope
is submitted for an unattended run on a machine with no visual toolchain.
The run is refused at admission, naming the missing tool — rather than
running and reporting a SKIP that reads like a pass.

**US4 — Existing project, untouched.** A project with no `verification`
block runs exactly as before: same gates, same artifacts, same output.

**US5 — Interrupted admission.** A previous run was SIGKILLed mid-admission
and left a registered throwaway worktree. The next run's preflight reclaims
it instead of accumulating stale registrations.

## Requirements

- **FR-1** `automation.json` MUST accept a `verification` block with
  `test`, `coverage`, `app`, `visual`, and `conformance` sub-blocks,
  validated by `validate-automation-config.sh`. An unknown key or an
  out-of-enum value MUST fail with a message naming the key.

- **FR-2** The block MUST be optional. A project without one MUST behave
  byte-identically to today, asserted by test.

- **FR-3** `coverage.baseline: none` (greenfield) MUST admit with **no**
  coverage artifact present at the base ref, and MUST enforce the absolute
  floor only, at `floor_enforced_at` (default `landing`).

- **FR-4** `coverage.baseline: admission` (brownfield) MUST capture the base
  ref's coverage at admission and MUST fail a run that either regresses by
  more than `max_regression_pct` or falls below the absolute floor.

- **FR-5** Floor values MUST come from a per-template preset file, with
  `automation.json` able to override. No global default may be hard-coded
  in a script.

- **FR-6** Coverage parsing MUST support `istanbul` and `lcov`. `cobertura`
  and `jacoco` MUST be rejected with an explicit "not implemented in C1"
  message — never silently treated as zero or as passing.

- **FR-7** When the contract puts UI in scope and `visual.skip_is_failure`
  is true, an `unattended` run MUST be refused at admission on a host whose
  visual toolchain is unavailable, naming the missing tool. Attended
  profiles MUST be unaffected.

- **FR-8** `conformance.required` MUST be validated but MUST remain
  inadmissible in C1, exactly as `runtime_conformance` verifiers are —
  its evaluator ships in C2.

- **FR-9** Driver preflight MUST `git worktree prune` so an interrupted
  admission cannot leak a registered worktree.

- **FR-10** Admission's `test.command` invocation MUST be recorded in the
  ledger's accounting, so a run's reported cost and time include it.

## Constraints — what NOT to build

- Do NOT add a driver-side visual/Playwright step. That is the ui-harness
  runner's job and a slice of its own; C1 enforces at admission instead.
- Do NOT implement the runtime conformance evaluator, and do NOT flip the
  `runtime_conformance`-inadmissible check. Both are C2.
- Do NOT hard-code any coverage floor in a script — presets only.
- Do NOT let an unsupported coverage format degrade to a pass. Refuse.
- Do NOT change attended-profile behaviour for projects without the block.
- Do NOT implement §5 bounded progress or §7 per-phase contracts here.

## Key Entities

- **`verification` block** — `automation.json`, schema-described, optional.
- **Coverage preset** — `shared/templates/<type>/verification-preset.json`,
  the only source of floor values.
- **Coverage summary** — the parsed `{line_pct, branch_pct}` produced by
  `scripts/lib/coverage-parse.sh` from an istanbul/lcov artifact.
- **Baseline record** — captured at admission for brownfield, stored in the
  ledger beside the config snapshot so a resume compares against the same
  numbers the run was admitted with.

## Success Criteria

- **SC-1** Greenfield: admits with no artifact; floor enforced at the
  landing gate; a run below the floor fails and does not land.
- **SC-2** Brownfield: baseline captured at admission; a regressing run
  fails; a below-floor run fails; a clean run lands.
- **SC-3** An unknown `verification` key, a bad enum, and an unimplemented
  parser each fail with their own named message.
- **SC-4** UI-in-scope + no visual toolchain + `unattended` ⇒ refused at
  admission naming the tool; the same project attended is unaffected.
- **SC-5** A project with no `verification` block produces byte-identical
  behaviour (asserted against the pre-change driver).
- **SC-6** Preflight prunes a stale worktree registration.
- **SC-7** Admission's `test.command` appears in the ledger accounting.
- **SC-8** All suites green; every SC has a regression that fails against
  the pre-change code.
