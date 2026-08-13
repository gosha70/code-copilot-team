# Spec: verification contract, increment C1 (#222) — rev 13

## User Scenarios

**US1 — Greenfield product build.** An unattended run against an empty
repository declares `verification.coverage` with `baseline: none` and a
floor. Admission does not demand a coverage artifact that cannot exist yet.
At the landing gate, coverage below the floor fails the run rather than
landing it.

**US2 — Brownfield feature.** `baseline: admission`. The preflight
initialiser runs the coverage command in a throwaway worktree, parses the
result before cleanup, and hands it back through the preflight-result
channel; the driver imports it into the ledger after preflight succeeds.
On an unattended run the admission bar also runs, contributing only its own
validation and accounting. A run that regresses
fails even if the floor is met; one below the floor fails even with no
regression.

**US3 — Half-configured contract.** A project sets `verification.visual`
or `verification.app`. Admission refuses with a message naming the key and
saying it is not supported in C1 — rather than accepting a setting that
enforces nothing.

**US4 — Existing project, untouched.** An attended run with no
`verification` block behaves identically to today. An unattended one differs
only by the two documented handoff exceptions (prune, admission time in the
cap).

**US7 — Resume does not re-decide policy.** A parked run is resumed after
someone edited the preset file and the branch moved on. The frozen contract
from the original preflight still governs: the baseline is not recaptured,
the floors do not move, and the attempt's clock starts before its own
admission.

**US5 — Interrupted admission.** A previous run was SIGKILLed mid-admission
leaving a registered throwaway worktree; preflight reclaims it.

**US6 — Refused admission leaves nothing.** A run that fails admission
creates no ledger, and no preflight-result file survives.

## Requirements

- **FR-1** `automation.json` MUST accept `verification.coverage`, validated
  by `validate-automation-config.sh`. Unknown keys and out-of-enum values
  MUST fail with a message naming the key.

- **FR-1a** `verification.test`, `.app`, `.visual` and `.conformance` MUST
  be **rejected** with "not supported in C1", naming the sub-block. They
  MUST NOT be accepted-and-ignored. Top-level `test.command` remains the
  single source for the test step. `conformance.required` is DERIVED from
  `verification.yaml` per #190 and is never operator-set.

- **FR-2** The block MUST be optional. An **attended** run without one MUST
  behave byte-identically, asserted against the pre-change driver.
  **Unattended** runs without the block get exactly two documented
  exceptions — the admission-path prune (FR-8) and admission time counting
  toward the cap (FR-9) — because both handoff items exist precisely to
  apply to unattended runs. No other difference is permitted.

- **FR-3** `baseline: none` MUST admit with no coverage artifact present and
  MUST enforce the absolute floor only, at `floor_enforced_at` (default
  `landing`).

- **FR-4** `baseline: admission` MUST capture the base ref's coverage during
  **preflight initialisation** (FR-7d) — the value `admission` names the
  POINT IN THE RUN, not the actor — and MUST fail a run that regresses beyond
  `max_regression_pct` or falls below the absolute floor. The comparison
  MUST use the frozen contract (FR-4a), not a live re-read.

- **FR-4a — the frozen coverage contract.** The **preflight initialiser**
  (FR-7d), not admission, MUST persist the FULLY RESOLVED contract —
  `command`, `preset_id`, `preset_sha256`, `parser`, `artifact`, effective
  floors, `max_regression_pct`, **`timeout_sec`**, `floor_enforced_at`, and
  the captured `baseline` (or null) — and every driver gate MUST read only
  that. `timeout_sec` is frozen with the rest (FR-5c): resolved live it
  could be widened after admission, and a later gate or resume could then
  run unbounded. `command` is included deliberately: a
  gate that must read "only the frozen block" cannot run coverage at all if
  the command lives elsewhere. The live preset file MUST NOT be re-resolved after admission,
  including on resume: freezing the preset NAME while its FILE stays
  editable would let a preset edit move the floor under an admitted run.

- **FR-4b — exact schema and arithmetic.** The `coverage` block is:

  | key | required | type / range | notes |
  |---|---|---|---|
  | `command` | yes | non-empty string | run in the project (or throwaway worktree at admission) |
  | `artifact` | yes | relative path | MUST resolve inside the project; absolute paths and `..` traversal are rejected |
  | `parser` | yes | `istanbul` \| `lcov` | `cobertura`/`jacoco` rejected: "not implemented in C1" |
  | `baseline` | yes | `none` \| `admission` | greenfield vs brownfield |
  | `min_line_pct` | at least one floor required | number 0–100 | |
  | `min_branch_pct` | at least one floor required | number 0–100 | |
  | `max_regression_pct` | **REQUIRED (effective) when `baseline: admission`**; rejected when `baseline: none` | number 0–100 | may come from the preset; a brownfield contract with no effective value is INADMISSIBLE, since FR-4 promises no-regression enforcement |
  | `timeout_sec` | no (preset, else `test.timeout_sec`) | number > 0 | FR-5c; the frozen contract always carries a positive effective value |
  | `floor_enforced_at` | no (default `landing`) | `landing` \| `phase` | |
  | `preset` | no | string | names `shared/templates/<preset>/verification-preset.json` |

  **Which metrics regression governs:** exactly those with a configured
  floor (`min_line_pct` and/or `min_branch_pct`). A metric with no floor is
  gated by neither floor nor regression, so the contract commits to
  precisely what it declares and adding a floor never silently activates an
  unrelated gate. Governed metrics are checked independently: either one
  regressing beyond the threshold fails.

  Regression is measured in **percentage POINTS** (`baseline_pct −
  measured_pct`), never relative percentage; the spec says so because the
  two differ by a factor of the baseline and a silent choice would be a
  wrong gate. A floor that is set but whose metric the parser cannot
  produce (e.g. `min_branch_pct` with an artifact carrying no branch data)
  MUST fail closed with a named message — never pass by absence.

- **FR-5b — preset provenance when no preset contributes.** FR-5 admits a
  config that supplies every floor explicitly with no resolvable preset,
  while FR-4a requires `preset_id` and `preset_sha256` in the frozen
  contract. In that case both MUST be `null` — recorded explicitly, so the
  frozen contract distinguishes "no preset contributed policy" from "a
  preset was resolved but not recorded". The schema MUST accept null for
  both, and that branch MUST be tested.

- **FR-5** Floors MUST resolve from `coverage.preset` naming
  `shared/templates/<preset>/verification-preset.json`, with
  `automation.json` overriding individual keys. A missing or unknown preset
  MUST fail closed at admission unless `automation.json` supplies every
  required floor. No floor literal may exist in any script.

- **FR-5a — coverage evidence MUST be fresh, and containment MUST be
  re-resolved on BOTH SIDES of execution.** Every baseline capture and every
  gate MUST: confirm the artifact path is inside the project **after
  resolving symlinks in every existing ancestor** — the lexical FR-4b check
  is not sufficient once the driver DELETES the path, since
  `coverage/out.json` escapes when `coverage` is a symlink out of tree; then
  remove the artifact; run the frozen `command` under FR-5c's bound; require
  it to **exit 0**; require the artifact to have been newly produced;
  **re-resolve containment AFTER the command exits and BEFORE reading** —
  the command is arbitrary project code and can replace a previously safe
  ancestor with an out-of-tree symlink between the two moments, so a single
  pre-execution check is a TOCTOU hole; and only then parse it,
  fail-closed. A coverage
  result MUST NOT be accepted from an artifact that predates the run of the
  command that was supposed to produce it — otherwise a previous passing
  report survives a command that fails without rewriting it, and the gate
  passes on stale evidence.

- **FR-5c — the coverage command MUST be bounded.** The frozen contract
  MUST carry a positive `timeout_sec` (from `coverage.timeout_sec`, else the
  preset, else the existing `test.timeout_sec`), and every capture and gate
  MUST execute the command under it. A timeout MUST fail the capture or gate
  closed. Without this an arbitrary hanging command blocks an unattended run
  indefinitely: the wall-clock cap is only evaluated BETWEEN operations, so
  it cannot interrupt one.

- **FR-5d — an unenforceable bound is refused, not ignored, on EITHER
  profile.** This repo has hosts with no `timeout(1)` (`run_tests()`
  degrades silently, and #205 showed a `timeout_sec` that enforced nothing).
  If no timeout mechanism is available, a run carrying a coverage block MUST
  refuse at preflight — **attended as well as unattended** — naming the
  missing tool. Warning and continuing for attended would contradict FR-5c's
  "every capture and gate", and an attended brownfield initialiser runs the
  same arbitrary command and can hang the same way. Refusal applies only to
  coverage-enabled runs; a no-block run is untouched (FR-2).

- **FR-6** Coverage parsing MUST support `istanbul` and `lcov`;
  `cobertura` and `jacoco` MUST be refused with "not implemented in C1",
  never treated as zero or as passing.

- **FR-7** The preflight initialiser MUST return the frozen contract, and
  the unattended admission bar MUST return its own accounting, through a
  machine-readable file written BEFORE the throwaway worktree is cleaned
  up. The driver MUST import it into the ledger only AFTER **every producer
  applicable to this path** has succeeded and the ledger exists, then remove
  it. Gating import on "admission succeeds" would leave
  `fresh-attended-block` with no defined import transition at all, since
  attended profiles never run admission; unattended paths additionally
  require the admission bar to pass.

- **FR-7a** A refused admission MUST leave no ledger and no preflight-result
  file (increment B's invariant preserved).

- **FR-7a0 — governance precedes project code.** On `fresh-unattended-block`
  the admission bar MUST pass BEFORE contract initialisation executes
  `coverage.command`. That command is arbitrary project code, and #193
  established that admission runs project commands only after config and
  governance checks — executing coverage first would run project code for a
  run governance is about to refuse. Producer order is normative, not
  incidental.

- **FR-7b0 — validation precedes execution.** On a resume whose config
  carries the block, the frozen contract MUST be loaded and validated
  BEFORE any producer runs. A missing or corrupt contract MUST fail closed
  without the project's `test.command` (or any other producer command)
  having been executed. Validation is a prerequisite, never a producer.

- **FR-7b — resume MUST NOT re-decide policy, when there is policy.**
  On resume of a run **whose config carries `verification.coverage`**, the
  driver MUST load and schema-validate the EXISTING frozen contract and MUST
  NOT recapture the baseline or overwrite it — otherwise the current branch
  and live preset would silently replace what the run was admitted against.
  A missing or corrupt contract in that case MUST fail closed.
  **A run without the block has no contract and its resume MUST proceed on
  the legacy path** — requiring one unconditionally would break the resume
  of every existing run.

- **FR-7d — contract creation is a preflight step, not part of admission.**
  Attended profiles never invoke admission, so admission cannot be the only
  thing that creates a contract or T6's attended gate would enforce a
  precondition nothing produces. When the block is present, a FRESH run of
  **either** profile initialises the contract at preflight (resolve preset,
  capture baseline if brownfield, freeze); unattended runs additionally run
  the admission bar. The lifecycle matrix in plan.md is normative.

- **FR-7c — pending events.** Any event produced BEFORE ledger
  initialisation (currently the prune warning) MUST be held and flushed only
  after the ledger exists. Journalling early would either fail on the
  missing directory or create durable state that survives a refused
  admission. On refusal such events MUST go to stderr and leave no ledger.

- **FR-8** The driver MUST `git worktree prune` iff **an applicable producer
  for this path will ATTEMPT isolated-worktree execution**. Admission
  usually does, so `fresh-unattended-noblock` and every `resume-unattended-*`
  path prune even with no `verification` block — one of FR-2's two stated
  exceptions. The decision MUST be made from **configured intent**, before
  anything runs: `CCT_ADMISSION_TEST_IN_PLACE=1` and non-git projects
  attempt no isolation and MUST NOT prune (`validate-spec.sh:462-466`).
  Whether `worktree add` later SUCCEEDS is not part of the trigger — the
  prune necessarily precedes the attempt, so that outcome is unknowable at
  decision time. Contract initialisation intends one only for brownfield.

  **T6 amendment (T7):** the coverage gate is a second worktree creator —
  it runs the frozen contract in a throwaway worktree at each enforcement
  point, on EVERY coverage-block path, and prunes immediately before its
  own `worktree add` (the same honest trigger, applied at the creation
  site). "Attended greenfield with a block MUST NOT prune" therefore held
  only before T6; post-T6 it prunes at the gate. The
  `CCT_ADMISSION_TEST_IN_PLACE=1` exception is SITE-scoped, not
  run-scoped: it suppresses only the admission-site prune, because
  in-place admission is the only isolation it opts out of — a
  coverage-block run under it still creates gate worktrees and still
  prunes at the gate. Only paths that create no worktree at all (every
  attended no-block path; in-place admission WITH no block) MUST NOT
  prune. Prune failure MUST be non-fatal and journalled (FR-7c) —
  including a NONZERO exit with no output, which is journalled with a
  fallback detail naming the exit code.

- **FR-9** Admission's `test.command` invocation MUST be inside the
  wall-clock budget, not merely recorded: a `duration_sec` field alone
  changes no cap arithmetic and would be bookkeeping dressed as
  enforcement. The clock origin is therefore **per path**: it is
  `ATTEMPT_START` (captured before any producer) **iff this path runs a
  pre-ledger producer**, and otherwise the existing `now`.

  This is what keeps FR-2 honest (rev 9): an attended no-block path runs no
  producer, so its clock behaviour is unchanged — an unconditional
  `ATTEMPT_START` would have started counting config/preflight time those
  runs exclude today. An attended run that OPTS INTO coverage does have its
  contract initialisation counted; that is a stated consequence of opting
  in, not an accident.

- **FR-9b — resume clocks start before resume's own admission.**
  `reset_run_clocks()` (#205/#210) sets `started_epoch` to *now*, and runs
  AFTER admission on the resume path — which would exclude the admission
  that just ran, reintroducing FR-9's bug on every resume. It MUST accept an
  explicit timestamp and be called with **this path's clock origin**:
  `ATTEMPT_START` for `resume-unattended-*`, and `now` for attended resumes,
  which run no producer. Existing callers pass `now`, preserving their
  behaviour.

- **FR-9a** The DRIVER MUST own the result-file path: create it, pass it to
  admission as an explicit argument, schema-validate the returned file,
  import atomically, and remove it on every exit path. It MUST NOT parse a
  path out of admission's diagnostic output.

- **FR-9c — the result file has an authoritative schema, discriminated by
  PATH.** `shared/schemas/preflight-result.schema.json` MUST be closed and
  versioned, and MUST carry a `path` discriminator over the five
  file-emitting paths, with closed `oneOf` branches stating exactly which
  sections each requires and forbids. `mode` plus optional sections is NOT
  sufficient: the schema cannot see profile or block presence, so it could
  not tell a fresh-unattended-with-block result (both sections required)
  from a fresh-unattended-no-block one (admission only), and
  `{schema_version, mode}` alone would validate as an empty result. The
  driver MUST independently compute the expected `path` from (mode,
  profile, block) and reject a file whose `path` disagrees.

  Sections then follow the path (the table in plan.md is normative):

  - `contract` MUST be present on a FRESH run with the block, on either
    profile, and MUST be **forbidden** on `resume`. That prohibition is what
    makes "a resume cannot overwrite frozen policy" checkable by the driver.
  - `admission` MUST be present only for **unattended** runs, which are the
    only ones that run admission and its `test.command`.

- **FR-9d — no producer, no file.** On a path the emission table marks as
  emitting nothing, the driver MUST NOT allocate a result path at all. "No
  file" MUST be literal rather than an empty placeholder that later has to
  be distinguished from a genuine result.

- **FR-9e — on resume, the expected path MUST come from the FROZEN config
  snapshot**, never from live `automation.json`. Path selection is
  security-relevant: reading it live would let someone delete the
  `verification.coverage` block between runs, turn `resume-unattended-block`
  into `resume-unattended-noblock`, and so skip the frozen-contract
  validation FR-7b exists to enforce. Profile and block presence on resume
  are properties of the ADMITTED run, not of the current file.

  **Attended paths MUST NOT emit synthetic zero-valued accounting**, and an
  attended resume MUST emit no result file at all. Requiring accounting
  everywhere would force an attended run to fabricate work it never did —
  an absent section means "did not run", which is the truth. A malformed,
  unknown-field, unversioned, contract-bearing-resume, or
  admission-bearing-attended file MUST be rejected without import.

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
- Do NOT re-resolve the preset after admission — not at a phase gate, not
  at landing, not on resume.
- Do NOT recapture the baseline on resume, and do NOT let a resume write a
  new frozen contract.
- Do NOT require a frozen contract from a run that never had one — a
  no-block resume must take the legacy path.
- Do NOT make admission the only creator of contracts; attended runs never
  reach it.
- Do NOT journal anything before the ledger exists.
- Do NOT accept `max_regression_pct` alongside `baseline: none`; it cannot
  be enforced there, and accepting it is the inert-config trap again.
- Do NOT let an unsupported coverage format degrade to a pass.
- Do NOT implement the conformance evaluator, §5 bounded progress, or §7
  per-phase contracts.

## Key Entities

- **`verification.coverage`** — the only sub-block C1 accepts.
- **Coverage preset** — `shared/templates/<preset>/verification-preset.json`,
  selected by an explicit portable `preset` key.
- **Coverage summary** — `{line_pct, branch_pct}` from
  `scripts/lib/coverage-parse.sh`.
- **Preflight result** — the machine-readable handoff file carrying the
  captured baseline and `test.command` accounting out of the throwaway
  worktree.

## Success Criteria

- **SC-1** Greenfield admits with no artifact; a below-floor run fails at
  the landing gate and does not land.
- **SC-2** Brownfield captures a baseline during preflight initialisation; a regressing run
  fails; a below-floor run fails; a clean run lands.
- **SC-3** Each rejected sub-block (`test`, `app`, `visual`, `conformance`),
  an unknown key, and an unimplemented parser fail with their own named
  message.
- **SC-4** A missing/unknown preset with incomplete floors fails closed; the
  same config with explicit floors admits.
- **SC-4a** Editing the preset file between admission and the gate does NOT
  change the enforced floor — the frozen contract wins, asserted.
- **SC-4b** Each schema rule of FR-4b fails with its own named message:
  absolute/traversing `artifact`, out-of-range percentage, no floor at all,
  `max_regression_pct` with `baseline: none`, and a floor whose metric the
  artifact lacks.
- **SC-4c** Regression arithmetic is percentage points: a baseline of 80
  and a measurement of 78 is a 2-point regression, asserted.
- **SC-5** An attended run with no `verification` block is byte-identical;
  an unattended one differs ONLY by the two documented exceptions,
  enumerated and asserted.
- **SC-5a** Resume with an edited preset file and a moved branch enforces
  the ORIGINAL frozen contract; the baseline is not recaptured.
- **SC-5b** Resume with a missing or corrupt frozen contract fails closed —
  **only when the config carries the block**. A no-block run's resume
  proceeds unchanged, asserted (this is the case rev 4 would have broken).
- **SC-5c** An ATTENDED fresh run with the block gets a contract and its
  gate enforces; the same project attended without the block is
  byte-identical.
- **SC-5d** The path-discriminated schema rejects each of these without
  importing anything: malformed JSON; an unknown field; a missing
  `schema_version`; an empty `{schema_version, path}` result; a `resume-*`
  path carrying `contract`; a `fresh-unattended-block` result MISSING its
  `contract`; an attended path carrying `admission`; and a file whose
  `path` disagrees with the one the driver computed.
- **SC-5e** Every row of the emission table is asserted: each of the five
  file-emitting paths validates and imports, and each no-producer row
  allocates no result path at all.
- **SC-5g** A resume whose frozen contract is missing or corrupt fails
  closed **without having executed `test.command`** — asserted by a command
  that would leave a marker if it ran.
- **SC-5i** On `fresh-unattended-block` with a config that fails governance,
  the coverage command NEVER executes — asserted with a coverage command
  that would write a marker.
- **SC-5j** An artifact path whose ancestor is a symlink out of the project
  is refused: an external sentinel file is neither deleted nor parsed —
  asserted BOTH for a pre-existing symlink and for one the coverage command
  CREATES during execution (the TOCTOU case).
- **SC-5l** A hanging coverage command is killed at `timeout_sec` and fails
  the capture/gate closed. On a host with no timeout mechanism, a
  coverage-enabled run refuses at preflight on BOTH profiles, while a
  no-block run on that host is unaffected.
- **SC-5n** Editing `coverage.timeout_sec`, the preset, or
  `test.timeout_sec` after initialisation does NOT change the frozen bound —
  the contract's value governs at every later gate and on resume.
- **SC-5m** A brownfield contract with no effective `max_regression_pct`
  (neither config nor preset) is inadmissible; line-only and branch-only
  regressions each fail independently; a metric with no configured floor is
  gated by neither floor nor regression.
- **SC-5k** A config with explicit floors and no preset freezes
  `preset_id: null`, `preset_sha256: null`, and admits.
- **SC-5h** A stale PASSING coverage artifact plus a command that exits
  non-zero without rewriting it FAILS the gate — at baseline capture and at
  the landing gate.
- **SC-5f** Deleting the live `verification.coverage` block between runs
  does NOT turn `resume-unattended-block` into a no-block path: the resume
  still demands its frozen contract (FR-9e).
- **SC-6** A refused admission leaves no ledger and no preflight-result
  file; a successful one imports **exactly the sections its path emits** —
  not "baseline and accounting" unconditionally, which is false for four of
  the seven paths.
- **SC-7** A stale worktree registration is pruned iff THIS RUN creates a
  throwaway worktree — `CCT_ADMISSION_TEST_IN_PLACE=1` suppresses only the
  admission-site prune (it opts out of admission isolation alone), asserted
  both ways below. Asserted reclaimed for
  `fresh-unattended-noblock` (admission, no block), `fresh-unattended-block`,
  `resume-unattended-*`, attended brownfield capture, and (T6 amendment, at
  the gate site) attended greenfield-with-block and `resume-attended-block`.
  Asserted NOT to prune on attended no-block paths and under
  `CCT_ADMISSION_TEST_IN_PLACE=1` with no block; asserted that the
  in-place + coverage-block combination STILL prunes at the gate (the
  exception is site-scoped). A failing prune is journalled — a silent
  nonzero exit with a fallback detail naming the code — and does not fail
  the run.
- **SC-7a** The wall-clock cap includes admission time on unattended paths:
  a run whose admission consumes most of the budget hits the cap sooner,
  asserted against the pre-admission timestamp rather than a logged field —
  on a FRESH run and, separately, on a RESUME.
- **SC-7c** An attended no-block run's clock origin is unchanged from
  today's behaviour (fresh and resume), asserted against the pre-change
  driver — no preflight or config time is newly counted.
- **SC-7b** A prune warning emitted before ledger init appears in the ledger
  after a successful admission, and appears only on stderr — with no ledger
  created — after a refused one.
- **SC-8** All suites green; every SC has a regression that fails against
  the pre-change code.

## Deferred from #222, explicitly

`visual.skip_is_failure` is NOT delivered by this slice. It requires a
driver-owned visual result at the landing gate (slice C3), which subsumes
the toolchain prerequisite. (Tracking: #222 carried this while C1 was in
flight; with C1 delivered and #222 closed by the owner, the deferral
tracks in #239.)
