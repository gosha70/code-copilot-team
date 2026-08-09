# Spec: verification contract, increment C1 (#222) — rev 2

## User Scenarios

**US1 — Greenfield product build.** An unattended run against an empty
repository declares `verification.coverage` with `baseline: none` and a
floor. Admission does not demand a coverage artifact that cannot exist yet.
At the landing gate, coverage below the floor fails the run rather than
landing it.

**US2 — Brownfield feature.** `baseline: admission`. Admission runs the
coverage command in its throwaway worktree, parses the result before
cleanup, and hands it back through the admission-result channel; the driver
imports it into the ledger after admission succeeds. A run that regresses
fails even if the floor is met; one below the floor fails even with no
regression.

**US3 — Half-configured contract.** A project sets `verification.visual`
or `verification.app`. Admission refuses with a message naming the key and
saying it is not supported in C1 — rather than accepting a setting that
enforces nothing.

**US4 — Existing project, untouched.** No `verification` block ⇒ identical
behaviour to today.

**US5 — Interrupted admission.** A previous run was SIGKILLed mid-admission
leaving a registered throwaway worktree; preflight reclaims it.

**US6 — Refused admission leaves nothing.** A run that fails admission
creates no ledger, and no admission-result file survives.

## Requirements

- **FR-1** `automation.json` MUST accept `verification.coverage`, validated
  by `validate-automation-config.sh`. Unknown keys and out-of-enum values
  MUST fail with a message naming the key.

- **FR-1a** `verification.test`, `.app`, `.visual` and `.conformance` MUST
  be **rejected** with "not supported in C1", naming the sub-block. They
  MUST NOT be accepted-and-ignored. Top-level `test.command` remains the
  single source for the test step. `conformance.required` is DERIVED from
  `verification.yaml` per #190 and is never operator-set.

- **FR-2** The block MUST be optional; a project without one behaves
  byte-identically, asserted against the pre-change driver.

- **FR-3** `baseline: none` MUST admit with no coverage artifact present and
  MUST enforce the absolute floor only, at `floor_enforced_at` (default
  `landing`).

- **FR-4** `baseline: admission` MUST capture the base ref's coverage during
  admission and MUST fail a run that regresses beyond
  `max_regression_pct` or falls below the absolute floor. The comparison
  MUST use the captured baseline, not a live re-read.

- **FR-5** Floors MUST resolve from `coverage.preset` naming
  `shared/templates/<preset>/verification-preset.json`, with
  `automation.json` overriding individual keys. A missing or unknown preset
  MUST fail closed at admission unless `automation.json` supplies every
  required floor. No floor literal may exist in any script.

- **FR-6** Coverage parsing MUST support `istanbul` and `lcov`;
  `cobertura` and `jacoco` MUST be refused with "not implemented in C1",
  never treated as zero or as passing.

- **FR-7** Admission MUST return its results — captured baseline and
  `test.command` accounting — through a machine-readable file written
  BEFORE the throwaway worktree is cleaned up. The driver MUST import it
  into the ledger only AFTER admission succeeds and the ledger exists, then
  remove it.

- **FR-7a** A refused admission MUST leave no ledger and no admission-result
  file (increment B's invariant preserved).

- **FR-8** Driver preflight MUST `git worktree prune`.

- **FR-9** Admission's `test.command` invocation MUST appear in the ledger's
  accounting, via FR-7's channel.

## Constraints — what NOT to build

- Do NOT accept any `verification` sub-block C1 does not enforce. Reject it
  by name.
- Do NOT implement `skip_is_failure` or claim it. A toolchain-presence check
  is a prerequisite, not the property: an installed Playwright does not
  prove the review ran, produced evidence, or avoided SKIP. It needs a
  driver-owned machine-readable visual result at landing — slice C3.
- Do NOT write to the ledger from admission. Refused admission must create
  nothing.
- Do NOT hard-code a coverage floor, or infer a template identity from
  adapter-specific files.
- Do NOT let an unsupported coverage format degrade to a pass.
- Do NOT implement the conformance evaluator, §5 bounded progress, or §7
  per-phase contracts.

## Key Entities

- **`verification.coverage`** — the only sub-block C1 accepts.
- **Coverage preset** — `shared/templates/<preset>/verification-preset.json`,
  selected by an explicit portable `preset` key.
- **Coverage summary** — `{line_pct, branch_pct}` from
  `scripts/lib/coverage-parse.sh`.
- **Admission result** — the machine-readable handoff file carrying the
  captured baseline and `test.command` accounting out of the throwaway
  worktree.

## Success Criteria

- **SC-1** Greenfield admits with no artifact; a below-floor run fails at
  the landing gate and does not land.
- **SC-2** Brownfield captures a baseline at admission; a regressing run
  fails; a below-floor run fails; a clean run lands.
- **SC-3** Each rejected sub-block (`test`, `app`, `visual`, `conformance`),
  an unknown key, and an unimplemented parser fail with their own named
  message.
- **SC-4** A missing/unknown preset with incomplete floors fails closed; the
  same config with explicit floors admits.
- **SC-5** No `verification` block ⇒ byte-identical behaviour.
- **SC-6** A refused admission leaves no ledger and no admission-result
  file; a successful one imports the baseline and the accounting.
- **SC-7** Preflight prunes a stale worktree registration.
- **SC-8** All suites green; every SC has a regression that fails against
  the pre-change code.

## Deferred from #222, explicitly

`visual.skip_is_failure` is NOT delivered by this slice and #222 stays open
for it. It requires a driver-owned visual result at the landing gate
(slice C3), which subsumes the toolchain prerequisite.
