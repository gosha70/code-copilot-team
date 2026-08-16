# Spec: driver-owned visual result + skip_is_failure, increment C3 (#239)

Requirements for #190 §6's visual verification and the one item increment
C1 deliberately left unmet. C2 (#242) made `runtime_conformance`
verifiers executable; this increment does the same for VISUAL evidence
and closes the silent-SKIP hole: today a missing Playwright degrades the
harness to an HTTP-200 smoke that writes `passed: true`, so an
unattended run can ship UI nobody ever looked at.

The lifecycle table and executable sequences in `plan.md` are normative;
this file states the requirements they satisfy.

## User Scenarios

- An operator maps `FR-12` ("the dashboard renders the empty state with a
  single primary CTA") to a `kind: visual` verifier and launches an
  unattended run. Admission checks that the UI bundle is real — a
  `DESIGN.md` with no unfilled placeholders, a `harness/`, a root
  `copilot:review` script — and refuses if it is not. At landing the
  driver starts the application, runs the harness itself in an isolated
  checkout, reads the criteria the harness answered, and lands only when
  every visual criterion is green.
- The build host has no Playwright. The harness degrades to an HTTP smoke
  and reports a pass. The run FAILS anyway: a skipped visual check is a
  failure, never a pass by absence.
- A UI regression makes the critic fail. The attended run parks naming
  `FR-12` and the actionable fixes; the operator fixes the UI, commits,
  and resumes; the recovery commit is reviewed and the gate re-runs.
- A project with no `kind: visual` mapping is unaffected — no harness, no
  DESIGN.md requirement, no visual gate.

## Constraints

- Whether visual verification is required is DERIVED from the finalized
  `verification.yaml`, never from a config flag (the #242 precedent).
- The driver owns execution: an agent's self-report is not evidence.
- All C1/C2 frozen-contract invariants (pinning, tamper, resume equality)
  apply unchanged to the extended contract object.
- The visual gate reuses C2's landing-gate epilogue: checkout integrity,
  proven teardown, and the single disposition path.
- Bounds are positive INTEGER seconds, as in C2.
- The visual command is the project's own mutable code and is treated as
  untrusted at every boundary it touches: execution isolation, filesystem
  containment, the environment it inherits, and cost accounting.

## Requirements

- **FR-1 — the `visual` block is accepted, and `required` stays derived.**
  `automation.json` MUST accept `verification.visual: { "command",
  "artifact", "url", "timeout_sec", "skip_is_failure"? }` (closed,
  schema-validated). `skip_is_failure` defaults to TRUE and may be set
  explicitly; `required_when_ui_in_scope` MUST be rejected by name with a
  message saying the requirement is derived from `verification.yaml`
  (see plan decision 1 — a deliberate, flagged deviation from #190 §6's
  sketch). `verification.visual` and `verification.app` are today
  rejected BY NAME as placeholders for this increment; both FLIP to
  accepted here. `verification.test` remains rejected by name.

- **FR-2 — `visual` is a verifier kind.** `verification.yaml` MUST accept
  `kind: visual` with a `criterion` (the same shape a
  `runtime_conformance` verifier uses). "UI is in scope" means exactly:
  at least one `FR-N` maps to a `kind: visual` verifier. The draft
  generator and the canonical capture MUST carry visual verifiers with
  their `statement_sha`.

- **FR-3 — the UI bundle is proven real, at admission AND at the gate
  (retires a DEFER).** When any FR maps to `kind: visual`,
  `validate-spec.sh --unattended` MUST require, with a named check per
  missing piece: `DESIGN.md` present and carrying ZERO `← REPLACE` /
  `← UPDATE` placeholders; a `harness/` directory; a root
  `copilot:review` script; `verification.visual` with a command,
  artifact, and `url`; and `verification.app` (FR-10). Because attended
  runs are NOT admission-checked, the SAME requirements MUST be
  re-asserted at the gate, using the same named messages: once early
  against the canonical checkout (before any project code runs) and
  AGAIN inside the execution root at the point of use — the C2 pattern
  of re-resolving at the gate rather than trusting admission. Every
  bundle component MUST be symlink-resolved-contained within the root
  being checked and of the expected type (a REGULAR file for `DESIGN.md`
  and the manifest declaring `copilot:review`, a REAL directory for
  `harness/`): a tracked symlink pointing outside that root MUST be
  refused, since handing the harness such a path would defeat the
  isolation while every path in the message still looked local.

- **FR-4 — the frozen visual contract.** The preflight initialiser MUST
  freeze, under the same pinning/tamper rules: the visual `command`,
  `artifact` (relative, contained), `url`, `timeout_sec`, the effective
  `skip_is_failure`, and the CRITERIA SET — every `kind: visual`
  criterion with its owning `FR-N` and `statement_sha`. Gates read only
  the frozen copy.

- **FR-5 — the driver runs the harness, in isolation.** At the landing
  gate the driver MUST execute the frozen visual command bounded by the
  frozen `timeout_sec`, in a DETACHED THROWAWAY WORKTREE at HEAD, never
  in the canonical checkout — the harness's screenshots and artifacts are
  expected outputs, and the integrity epilogue requires the canonical
  checkout to stay pristine. Isolation MUST match C1's, not merely a
  change of working directory: `CCT_PROJECT_DIR` and `CCT_SPECS_DIR`
  rebound to the execution root, `OLDPWD` dropped, and C2's handoff
  variables still stripped. No path the driver hands the harness may
  point into the canonical checkout or the ledger — the request document
  lives in a run-scoped private directory and `DESIGN_MD` resolves inside
  the worktree. The frozen artifact path MUST be symlink-resolved-
  contained within the execution root before deletion and again after
  execution, deleted with a CHECKED deletion, and required to be a NEWLY
  produced REGULAR file. A non-zero exit, a timeout, an escaped, missing,
  or unparseable artifact is a visual-gate FAILURE.

  The execution root MUST be created AFTER the gate's other arbitrary
  execution — the deterministic verifiers and the evaluator — and
  revalidated at the point of use: its HEAD equal to the gate HEAD, its
  porcelain status EMPTY, and the bundle containment/type checks
  repeated inside it. A worktree created earlier would stand registered
  and discoverable while project code ran, and could have its harness or
  manifest replaced after being checked, so that the driver collected
  evidence from a substitute. The request document MUST likewise be
  authored at the point of use, after that revalidation, since it names
  a path inside the execution root.

  The application under test is project code and stays ALIVE across the
  visual block, so it can reach the execution root after validation.
  After the harness returns and BEFORE any verdict is honoured, the gate
  MUST therefore re-verify that every TRACKED file in the execution root
  still matches the gate HEAD (untracked paths excepted — the harness's
  own outputs are untracked and are what the run produced).

  The boundary this establishes MUST be documented as stated, not
  implied: it defends against PERSISTENT changes to TRACKED bundle
  files. It does NOT defend against active same-user interference while
  the gate runs — a live app can create or replace the untracked
  feedback artifact or transcript, which this check exempts by design,
  and a tracked swap-and-restore is equally undetected. A real isolation
  boundary for both the app and the harness is deferred (plan
  decision 10).

- **FR-6 — a SKIP is a failure, and the reading is ordered.** The harness
  artifact MUST declare whether the visual pass actually ran, via `mode`
  (`"full"|"degraded"`) and `skipped: [string]`. The gate MUST apply, in
  order: closed-shape validation (with `mode`/`skipped` OPTIONAL in the
  shape, so an older artifact is interpreted rather than rejected);
  cross-field rules — absent `mode` ⇒ degraded, absent `skipped` ⇒ `[]`,
  `mode: "full"` with a non-empty `skipped` list is MALFORMED, and an
  explicit `mode: "degraded"` with an EMPTY `skipped` list is likewise
  MALFORMED, since the failure message must be able to name what was
  skipped; then `skip_is_failure`. When `skip_is_failure` is true (the
  default), an effective mode other than `"full"` MUST fail the gate even
  if the artifact reports `passed: true` — the HTTP-smoke fallback is
  exactly the case this exists for — naming what was skipped (or, for an
  undeclared mode, saying that the harness declared nothing) and how to
  enable it.

- **FR-7 — visual evidence is per-criterion, identity-bound, waiver-
  honest, and atomically published.** The artifact MUST echo every frozen
  visual criterion exactly once, carrying its `fr`, `statement_sha`,
  `criterion`, a `verdict` of `pass | fail | skip`, and `evidence`; the
  driver MUST validate this as an exact identity multiset of the frozen
  set and REFUSE missing, duplicated, altered, or invented entries.

  A degraded harness MUST answer criteria it did not evaluate as `skip`,
  never as `pass`, and `skip` is legal only when the effective mode is
  not `"full"`. A `skip` MAY count green ONLY under an explicit frozen
  `skip_is_failure: false`. The waiver is a property of the INVOCATION,
  not only of individual verdicts: `verification-results.json` MUST
  record the invocation's `mode`, its `skipped` list, and
  `waived_by_policy`, and EVERY visual entry from a waived invocation
  MUST carry `waived: true` whatever its own verdict — otherwise a
  degraded run whose evaluated criteria all passed would read as fully
  verified. The landing journal MUST report the policy waiver whenever it
  applies, including when no criterion was itself a skip.

  The global `passed` flag is a summary and MUST NOT be copied across
  criteria as if it were per-FR proof; it MUST equal "every criterion
  verdict is `pass`", and an artifact whose summary contradicts its
  criteria is malformed.

  Evidence imported from the execution root into the ledger MUST be
  published like every other ledger write — destination proven absent,
  written to a temp file, validated, renamed into place, all BEFORE the
  worktree is removed — so a failed import can never leave an earlier
  run's PASS in place to be read as this run's evidence.
  `verification-results.json` MUST carry the visual verifiers as
  `kind: visual` entries per `FR-N`, with the critic's summary and
  actionable fixes as evidence. An FR is green iff ALL its mapped
  verifiers — deterministic, conformance, and visual — are green.

- **FR-8 — dispositions and resume.** Visual-gate failures use
  `visual_gate` with the C1/C2 recovery contract: parks record
  `parked_head`, resume re-runs the gate, and anything committed past the
  reviewed HEAD needs its own review PASS first (the shared arm).

- **FR-9 — metered on the unmetered path; the cost channel is never
  exposed.** The cost channel MUST NOT be handed to the project's visual
  command: a mutable harness given the authoritative cost path could
  report zero and suppress the conservative estimate. The harness
  invocation MUST therefore debit through the unmetered path — the
  conservative estimate when estimates are active, and nothing when they
  are not. C3 offers NO measured-cost path; a trusted provider-invoked
  critic is deferred (plan decision 8), and documentation MUST say the
  visual invocation is estimate-metered rather than implying parity with
  reviewers. The ledger write is CHECKED and precedes any disposition; an
  unrecorded cost disposes `cost_accounting_failed`.

- **FR-10 — one application lifecycle for both runtime kinds.** The
  application under test MUST be declared once at `verification.app`
  (command, readiness, stop bound, optional interface) and frozen once.
  `verification.conformance.app` MUST be rejected by name with a
  migration message. The app is required iff conformance or visual is in
  the frozen contract; the gate MUST launch it once before the first
  consumer and stop it once after the last, and the mid-sequence
  integrity check between consumers MUST NOT tear it down — teardown
  belongs to failure exits and the final epilogue only. A visual-only
  contract gets a running application; a contract with both does not get
  two.

- **FR-11 — the shipped harness satisfies the contract.** The runner MUST
  accept the driver's request (criteria, browser base URL, DESIGN.md
  path), declare its `mode`/`skipped`, and emit per-criterion verdicts.
  The Playwright-missing path MUST declare `mode: "degraded"` naming what
  it skipped, and the no-API-key path MUST stop reporting a pass. Because
  `CRITIC=agent` writes only a request and exits 0, it MUST refuse by
  name when invoked with a driver request rather than exit successfully.

- **FR-12 — the browser base URL is frozen, not inferred.** The visual
  block MUST carry an explicit `url`; the driver MUST NOT derive it from
  `app.interface` or from readiness, which are evaluator- and
  probe-facing and may legally be an API base or a health endpoint. The
  `url` MUST be http(s) and SAME-ORIGIN with the app's resolved
  interface, so the harness cannot be pointed at a host the driver never
  launched, and it is exported to the invocation as the browser base.
  Same origin is not the same process, so the `url` MUST also join the
  launch-binding proof: it MUST NOT answer before the app is launched
  (an unprovable probe is equally a refusal), and it MUST answer after
  launch while the spawned process group is alive. Otherwise a stale
  responder could serve the UI path while the launched command does
  nothing, and the visual evidence would describe the previous
  deployment.

## Explicitly deferred

- §5 bounded progress / multi-round visual loops: C3's gate is
  single-invocation per landing gate, like C2's evaluator. The harness's
  own internal iteration is unchanged.
- §7 per-phase contracts; §13/D recovery.
- A trusted provider-invoked visual critic with MEASURED cost (provider
  selection, capability/health screening, request placeholder, result
  integration, resume behaviour) — a slice of its own.
- The two unowned admission DEFER items (schema-migration allowlist,
  mid-flight credential/secret enumeration) stay unowned.

## Success criteria

- **SC-1** A finalized artifact with one `kind: visual` FR admits iff the
  visual block is present AND the UI bundle is real; each of {missing
  block, missing `url`, missing `verification.app`, missing DESIGN.md,
  placeholder-bearing DESIGN.md, missing harness/, missing
  `copilot:review`} refuses with a named check. No visual mapping ⇒ none
  of it is required.
- **SC-2** `required_when_ui_in_scope` is rejected by name; the accepted
  block round-trips the schema; `skip_is_failure` defaults to true.
- **SC-3** The frozen contract pins command, artifact, url, timeout,
  `skip_is_failure`, and criteria; editing the config or artifact after
  initialisation changes nothing at the gate; drift disposes.
- **SC-4** A degraded harness result FAILS the gate, naming the skip and
  the remedy; the same result lands when `skip_is_failure` is explicitly
  false, and its criteria are then recorded green WITH `waived: true`
  and a `skip` detail — never as passes.
- **SC-5** A result with no `mode` is treated as degraded: it fails under
  the default, its message says the harness declared nothing, and it can
  land only when `skip_is_failure` is explicitly false. `mode: "full"`
  with a non-empty `skipped` list, and `mode: "degraded"` with an empty
  one, are both rejected as malformed on every setting.
- **SC-6** A failing critic parks/terminates naming the FR and the
  actionable fixes — INCLUDING when it exits non-zero, as long as the
  artifact it wrote is usable; a passing one lands with its evidence in
  `verification-results.json`.
- **SC-7** The artifact must be a newly produced regular file contained
  in the execution root: a stale artifact never counts as this run's
  evidence, and one whose path escapes via a symlink planted DURING
  execution is refused.
- **SC-8** The harness invocation debits the conservative estimate when
  estimates are active (and nothing when they are not); a harness that
  writes a zero cost to a guessed path cannot suppress that debit; a
  refused ledger write disposes `cost_accounting_failed`.
- **SC-9** All suites green; every SC regression verified to fail against
  the pre-change code (mutation runs recorded in the PR).
- **SC-10** A harness that writes screenshots and scratch files into its
  working tree still lands: the canonical checkout is untouched, the
  integrity epilogue passes, and the evidence is present in the ledger
  after the worktree is gone. A harness that inspects its environment
  sees `CCT_PROJECT_DIR`/`CCT_SPECS_DIR` bound to the execution root and
  no `OLDPWD`, and is handed no path into the ledger or the canonical
  checkout.
- **SC-11** A visual-only frozen contract (no conformance) launches the
  application, has it ALIVE when the harness runs, and stops it exactly
  once; a contract with both kinds launches exactly one application, and
  the mid-sequence integrity checkpoint after the conformance block
  leaves it running. `verification.conformance.app` is rejected by name.
- **SC-12** An artifact carrying only a global `passed`, or one whose
  criteria are missing/duplicated/altered/invented against the frozen
  set, is REFUSED — never expanded into per-FR verdicts. So are
  `mode: "full"` with a `skip` verdict, and a `passed` that contradicts
  its criteria in either direction.
- **SC-13** The shipped runner declares `mode: "degraded"` with a named
  `skipped` list on the Playwright-missing and no-API-key paths, emits
  per-criterion verdicts on the vision path, and refuses by name under
  `CRITIC=agent` when a driver request is present.
- **SC-14** An ATTENDED run with a visual mapping and an incomplete
  bundle fails at the gate with the same named message admission would
  have produced, before the harness command runs.
- **SC-15** A stale `critique-feedback.json` already in the ledger is
  never read as this run's evidence: with a passing stale file in place
  and an import that cannot complete, the gate fails rather than landing
  on it.
- **SC-16** A stale responder answering the visual `url` before launch
  refuses the gate, and a launched command that never serves the `url`
  fails readiness — proving the URL is bound to THIS run's process
  group, not merely to the right origin.
- **SC-17** A failing integrity checkpoint between consumers leaves no
  surviving app process group; a successful one leaves the app running
  for the visual block. A failure DURING the visual block — where the
  execution root does exist — additionally leaves no worktree directory
  and no stale registration.
- **SC-18** An inherited `VG_WT_DIR`/`VG_VIS_PRIV` in the environment is
  never deleted by the driver: with both pointing at a host-owned
  directory that the driver did not create, an early failure leaves it
  intact. Conversely, a worktree directory the driver DID create but
  could not register (`git worktree add` fails) is still removed — the
  two setup stages are tracked separately, so partial setup leaks
  nothing.
- **SC-20** A bundle component that resolves outside the execution root
  — a tracked `DESIGN.md` symlinked to the canonical checkout — is
  refused by name, at admission and at both gate checks, before the
  harness runs.
- **SC-23** A PERSISTENT change to a TRACKED file in the execution root
  cannot produce forged evidence: a deterministic verifier that writes
  to the path the worktree will occupy is caught by the point-of-use
  revalidation, and an app that modifies a tracked file during the
  harness run is caught by the post-run HEAD re-verification, which
  refuses instead of honouring the verdict. Untracked interference is
  outside the boundary and is asserted only as documentation (the
  README and plan decision 10 state it).
- **SC-24** A worktree whose `git worktree remove -f` fails is still
  fully released — directory gone AND no stale registration left behind
  — and a release that cannot be completed keeps its ownership so the
  EXIT handler retries it.
- **SC-21** A degraded invocation whose evaluated criteria all report
  `pass`, landed under `skip_is_failure: false`, records
  `waived_by_policy` with its `mode` and `skipped` list, marks every
  visual entry `waived: true`, and says so in the landing journal — it
  never reads as fully verified.
- **SC-22** In a combined conformance+visual run, a teardown failure
  DURING the visual block is disposed naming the visual block, not
  conformance.
- **SC-19** A post-freeze edit to `verification.visual` or
  `verification.app` changes nothing at the gate, including in the
  attended bundle prerequisite — the gate reads config only from the
  frozen contract, and the shared helper checks bundle FILES only.
