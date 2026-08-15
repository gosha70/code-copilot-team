# Spec: runtime conformance evaluator, increment C2 (#242) — rev 4

Requirements for #190 §6's runtime conformance evaluator and increment-B
handoff items 1/2/5. C1 (#222) froze the coverage contract; this
increment makes `runtime_conformance` verifiers executable and makes
`landed` mean "every mapped verifier green", recorded as evidence.

The lifecycle table and executable sequences in `plan.md` are normative;
this file states the requirements they satisfy.

## User Scenarios

- An operator maps `FR-23` to a `runtime_conformance` verifier ("Cancel
  button aborts the job and the row shows 'cancelled'") and launches an
  unattended run: admission verifies the evaluator is configured and
  healthy, the build proceeds, and at landing the evaluator clicks
  through the RUNNING app; the run lands only when that criterion (and
  every other mapped verifier) is green — the evidence ledger says so.
- The same run with the evaluator's provider down refuses at admission
  (unattended) or parks `provider_unavailable` at the gate (attended) —
  never a silent skip.
- A criterion fails: the attended run parks naming `FR-23`; the operator
  fixes the app, commits, resumes; the recovery commit is reviewed
  (commit-bound recovery), the gate re-runs, the run lands.
- A project with no `runtime_conformance` mappings needs no conformance
  block and no evaluator. Its deterministic verifiers (if any) are now
  EXECUTED at the landing gate — the intentional C2 change (SC-8). A
  project with neither a coverage block nor a finalized
  `verification.yaml` runs byte-identically to C1.

## Constraints

- Runs with neither a coverage block nor a finalized
  `verification.yaml` MUST be byte-identical to C1. Deterministic-only
  runs need no conformance block or evaluator; their one intentional
  delta from C1 is the executed deterministic-verifier gate (FR-7,
  SC-8) — documented and tested, never silent.
- One evaluator invocation per landing gate (no §5 loops in C2).
- The evaluator is a configured provider in the reviewers' trust class;
  no new sandboxing beyond app process-group containment.
- All C1 frozen-contract invariants (pinning, tamper, resume equality)
  apply unchanged to the extended contract object.
- No pi-runtime surface changes in C2.

## Requirements

- **FR-1 — the `conformance` block is accepted, and `required` stays
  derived.** `automation.json` MUST accept
  `verification.conformance: { "evaluator": "<provider>", "app": { … } }`
  (schema-validated, closed). An operator-supplied `required` key MUST be
  rejected by name with a message saying it is derived from
  `verification.yaml` (#190 §6). `test`/`app`(top-level)/`visual` remain
  rejected by name (C3+). Runs without the block require no evaluator
  and no conformance machinery (the deterministic-gate delta is FR-7's,
  not this block's).

- **FR-2 — `required` derivation.** Conformance is REQUIRED for a run iff
  `specs/<feature>/verification.yaml` maps at least one `FR-N` to a
  `kind: runtime_conformance` verifier. The derivation MUST read the
  finalized artifact (statement_sha-validated at admission), never
  `automation.json`.

- **FR-3 — admission flips to availability (handoff item 2).**
  `validate-spec.sh --unattended` MUST stop refusing `runtime_conformance`
  mappings outright. Instead: if any FR maps to `runtime_conformance`, the
  run is admissible only when `verification.conformance` is present, its
  `evaluator` resolves in providers.toml, that provider DECLARES the
  runtime-conformance capability — a `conformance_command` template
  (FR-5) — and it passes the same health check reviewers use. Health
  alone does not prove capability: a healthy reviewer-only provider
  (review `command` but no `conformance_command` — e.g. a read-only
  review profile or a plain prompt-in/text-out adapter) can only
  fabricate runtime evidence and MUST refuse by name. A mapped
  requirement with a missing, unresolvable, capability-less, or
  unhealthy evaluator MUST refuse admission (exit 1, no ledger) with a
  named check per missing piece. Runs with no `runtime_conformance`
  mappings MUST NOT require the block (evaluator is not universally
  mandatory — #190 §3).

- **FR-4 — the frozen verification contract.** The preflight initialiser
  (C1's T5) MUST freeze, alongside the coverage contract and under the
  same pinning/tamper rules (in-memory pin, semantic resume equality,
  drift disposes), BOTH verification dimensions of the finalized
  artifact:
  - `verifiers` — every `kind: deterministic` verifier as
    `{fr, statement_sha, test, metric}`, plus the resolved
    `timeout_sec`;
  - `conformance` — the evaluator provider id, the app-launch contract
    (FR-6), the RESOLVED evaluator-facing app interface
    (`app.interface`, else `ready.url` — FR-6), `timeout_sec`, and the
    CRITERIA SET — every `runtime_conformance` criterion with its
    owning `FR-N` and `statement_sha` (present iff the derived
    requirement holds).
  Gates MUST read only the frozen copies; editing `verification.yaml` or
  `automation.json` after initialisation moves nothing. The
  preflight-result schema's closed `contract` object gains optional
  closed `verifiers` and `conformance` sub-objects (each absent when its
  input is absent). Because freezing now happens whenever the finalized
  artifact exists, the contract lifecycle (preflight paths, resume
  prerequisite, rollback, initialiser trigger) keys on the
  verification-wide predicate — plan design decision 3 is normative.

- **FR-5 — the evaluator contract (fresh context, running app).** The
  evaluator is a providers.toml provider invoked through the SAME
  request/adapter machinery reviewers use — providers consume a request
  document and emit stdout; nothing else may be assumed of them
  (existing providers are prompt-in/stdout-out and may be explicitly
  read-only). Once per landing gate:
  - the provider's eligibility contract is an EXPLICIT
    `conformance_command` — an evaluator-specific command template
    (request-file placeholder, same healthcheck field), distinct from
    the review `command`, whose flags/tooling the operator grants for
    exercising a running application (the review command's read-only
    sandbox assumptions do not transfer). Declaring it IS the
    provider's `runtime_conformance` capability (FR-3); the driver
    never invokes a review `command` as an evaluator;
  - the driver AUTHORS a conformance request document into the ledger
    carrying the frozen criteria `[ {fr, statement_sha, criterion} … ]`,
    the FROZEN evaluator-facing app interface (FR-4/FR-6 — the resolved
    address of the running app; nothing mutable), and a Required Output
    Format section demanding EXACTLY ONE fenced JSON block
    `{ "criteria": [ {fr, statement_sha, criterion,
    verdict: "pass"|"fail", evidence} … ] }` — every verdict echoing
    its FULL frozen tuple;
  - the request path is substituted at the `conformance_command`
    template's request-file placeholder; the adapter captures stdout,
    bounded by the frozen `timeout_sec`, and writes
    `CCT_REVIEW_COST_FILE` (FR-8);
  - the ADAPTER extracts the fenced JSON block from the captured stdout
    and writes the result file — the evaluator itself never writes into
    the checkout or the ledger (read-only providers are admissible).
  The evaluator exercises the RUNNING APPLICATION, not the diff
  (#190 §6). The driver MUST ensure the result path is absent before
  invocation, and the result MUST be produced from THIS invocation's
  capture (freshness). A non-zero provider exit, a timeout, no fenced
  JSON block, more than one, or a result that is unparseable,
  schema-invalid, or not an EXACT identity multiset of the frozen
  criteria — any criterion missing, duplicated, phantom, or modified —
  MUST be treated as evaluator failure, never as a pass (fail closed; a
  criterion cannot pass by absence or by alteration).

- **FR-6 — driver-owned app lifecycle.** The driver, not the evaluator,
  starts and stops the application: `conformance.app` carries
  `{ "command": "...", "ready": { "url" | "command", "timeout_sec" },
  "stop_timeout_sec", "interface"? }`. The evaluator-facing app
  interface is `app.interface` when present, else `ready.url`; a
  command-only-readiness config with no `app.interface` gives a capable
  evaluator no address for the running application and MUST be rejected
  by name at config validation (both profiles). Readiness MUST be bound to the launched
  instance: BEFORE the app is started, the ready probe MUST FAIL — an
  already-answering responder cannot be attributed to this launch and
  fails the gate; after launch the probe must succeed within its bound
  AND the spawned process group must still be alive at the moment it
  succeeds (a stale responder must not vouch for a dead launch); a
  failed probe is an evaluator-gate failure, fail closed. Stop the
  WHOLE process group afterwards with
  TERM→KILL escalation (the cp_run_bounded discipline) — a surviving
  descendant must not outlive the gate. App stdout/stderr are captured to
  the ledger.

- **FR-7 — the landing verifier ledger (handoff item 1).** `landed`
  requires every mapped verifier green. At the landing gate (after the
  coverage gate, before finalize/push/PR) the driver MUST write
  `verification-results.json` into the run ledger: one entry per `FR-N`
  of the frozen artifact, with PER-VERIFIER results. `kind:
  deterministic` verifiers are each EXECUTED at the gate — their FROZEN
  `test` command, bounded by the frozen timeout, exit 0 = green
  (admission's resolution was the screen; THIS execution is the
  decision) — a deterministic verifier is never inferred green from the
  generic `test.command` gate. `runtime_conformance` entries carry the
  evaluator's per-criterion verdict and evidence. An FR is green iff ALL
  its mapped verifiers are green. Any non-green or unresolved entry MUST
  dispose: park (attended) / `terminated_policy` (unattended), naming
  the FR(s) and verifier(s). The summary artifact repeats the table.

- **FR-8 — metered evaluator invocations (handoff items 3/5).** Each
  evaluator invocation debits the SAME caps as reviewers: a cost written
  via the adapter cost channel is measured; a missing/invalid/negative
  cost is unmetered and debits the conservative per-invocation estimate
  when estimates are active. Evaluator wall-clock counts toward the run
  cap; `check_caps` runs after the gate. In-band cost text in the
  evaluator's stdout is never parsed as a measurement.

- **FR-9 — dispositions and resume.** Evaluator-gate failures use a
  dedicated reason (`conformance_gate`) with the C1 recovery contract:
  parks record `parked_head`; resume re-runs the gate; anything committed
  past the reviewed HEAD needs its review PASS first (the existing
  commit-bound recovery arm applies unchanged). An evaluator provider
  that is unhealthy AT THE GATE, no longer resolvable, or no longer
  declaring `conformance_command` disposes `provider_unavailable` (its
  existing resume arm re-checks all three).

- **FR-10 — attended parity.** Attended runs with a conformance
  requirement enforce the same gate (park instead of terminate). Attended
  runs are NOT admission-checked (no admission exists there), so a
  missing/unhealthy evaluator surfaces at the gate, not earlier.

- **FR-11 — checkout integrity across the gate.** The landing verifier
  gate executes in the working checkout. Before verifier/app execution
  the FULL porcelain status — INCLUDING untracked files — MUST be empty
  and the gate HEAD captured; after the evaluator finishes and the app
  is stopped, HEAD MUST be unchanged and the full porcelain status
  empty again. Any mutation of the checkout — a tracked edit OR a new
  untracked file, by the app, a verifier command, or the evaluator — is
  a control-system failure: dispose `git_anomaly` naming the paths; the
  mutation MUST never reach the `git add -A` summary commit.

## Explicitly deferred

- Visual (`skip_is_failure`, driver-owned visual result): #239 (C3).
- §5 bounded progress / multi-round evaluator loops: the C2 evaluator is
  single-invocation per landing gate; scored-loop iteration is deferred
  with §5.
- §7 per-phase contracts; §13 recovery (increment D).
- Admission DEFER items "schema-migration allowlist" and "mid-flight
  credential/secret enumeration": not owned by C2; they need their own
  increment decision (recorded on #242).

## Success criteria

- **SC-1** A finalized `verification.yaml` with one `runtime_conformance`
  FR admits iff the conformance block is present and its evaluator is
  healthy AND capability-declaring; each of {missing block, unresolvable
  provider, healthy reviewer-only provider (no `conformance_command`),
  unhealthy provider} refuses with a named check. A yaml with no such
  mapping admits without the block (no evaluator required).
- **SC-2** An operator-supplied `conformance.required` is rejected by
  name; a command-only-readiness config without `app.interface` is
  rejected by name; the accepted block (including `app.interface`)
  round-trips the schema.
- **SC-3** The frozen contract pins the deterministic verifier set,
  evaluator, app contract, resolved app interface, and criteria;
  editing `verification.yaml` or
  the config after initialisation changes nothing at the gate
  (asserted), and disk drift disposes exactly as C1's tamper rule does.
  A conformance-only run (no coverage block) freezes and takes a
  `-block` preflight path; resuming it without the frozen contract
  refuses (the lifecycle keys on the verification-wide predicate).
- **SC-4** The evaluator receives the frozen criteria and app interface
  via the driver-authored request document (asserted against a
  provider-template-shaped stub entry) and the RUNNING app (readiness
  proven); the adapter-extracted verdicts land in
  `verification-results.json` per FR; a failing criterion
  parks/terminates naming the FR; a capture with no fenced JSON block,
  multiple blocks, a non-zero exit, or a result that is not an exact
  identity multiset of the frozen criteria (missing, duplicated,
  phantom, or modified entries) fails closed (never pass-by-absence or
  -alteration).
- **SC-5** App lifecycle: a ready probe that already succeeds BEFORE
  launch fails the gate (unattributable responder — asserted with a
  pre-existing server and a sleep-marker launch command); ready-probe
  timeout fails the gate; a probe that succeeds while the spawned
  process group is dead fails the gate; after the gate no descendant of
  the app process group survives (asserted with a marker child, the
  cp_run_bounded pattern).
- **SC-6** A measured evaluator cost debits `cost_usd`; an unmetered one
  debits the estimate (flagged); in-band cost text is ignored; the cap
  parks when crossed at the gate (event order proven, C1 pattern).
- **SC-7** Attended and unattended dispositions: park with `parked_head`
  + commit-bound recovery resume; terminate with triage naming the FR.
- **SC-8** A frozen deterministic verifier whose command fails blocks
  landing (named in `verification-results.json`) even when the generic
  `test.command` gate is green — execution, not inference.
- **SC-9** A checkout mutation during the gate — a tracked-file edit OR
  a NEW UNTRACKED file created by the app or the evaluator — disposes
  `git_anomaly` naming the path, and the mutation never reaches the
  `git add -A` summary commit (both cases exercised).
- **SC-10** All suites green; every SC regression verified to fail
  against the pre-change code (mutation runs recorded in the PR).
