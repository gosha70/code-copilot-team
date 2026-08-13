# Spec: runtime conformance evaluator, increment C2 (#242) — rev 2

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
- A project with no `runtime_conformance` mappings runs byte-identically
  to C1 — no block required, no evaluator, no new behavior.

## Constraints

- Runs without a conformance requirement MUST be byte-identical to C1.
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
  rejected by name (C3+). Runs without the block behave byte-identically
  to C1 (the FR-2 discipline of C1 carries over).

- **FR-2 — `required` derivation.** Conformance is REQUIRED for a run iff
  `specs/<feature>/verification.yaml` maps at least one `FR-N` to a
  `kind: runtime_conformance` verifier. The derivation MUST read the
  finalized artifact (statement_sha-validated at admission), never
  `automation.json`.

- **FR-3 — admission flips to availability (handoff item 2).**
  `validate-spec.sh --unattended` MUST stop refusing `runtime_conformance`
  mappings outright. Instead: if any FR maps to `runtime_conformance`, the
  run is admissible only when `verification.conformance` is present, its
  `evaluator` resolves in providers.toml, and that provider passes the
  same health check reviewers use. A mapped requirement with a missing,
  unresolvable, or unhealthy evaluator MUST refuse admission (exit 1, no
  ledger) with a named check. Runs with no `runtime_conformance` mappings
  MUST NOT require the block (evaluator is not universally mandatory —
  #190 §3).

- **FR-4 — the frozen verification contract.** The preflight initialiser
  (C1's T5) MUST freeze, alongside the coverage contract and under the
  same pinning/tamper rules (in-memory pin, semantic resume equality,
  drift disposes), BOTH verification dimensions of the finalized
  artifact:
  - `verifiers` — every `kind: deterministic` verifier as
    `{fr, statement_sha, test, metric}`, plus the resolved
    `timeout_sec`;
  - `conformance` — the evaluator provider id, the app-launch contract
    (FR-6), `timeout_sec`, and the CRITERIA SET — every
    `runtime_conformance` criterion with its owning `FR-N` and
    `statement_sha` (present iff the derived requirement holds).
  Gates MUST read only the frozen copies; editing `verification.yaml` or
  `automation.json` after initialisation moves nothing. The
  preflight-result schema's closed `contract` object gains optional
  closed `verifiers` and `conformance` sub-objects (each absent when its
  input is absent). Because freezing now happens whenever the finalized
  artifact exists, the contract lifecycle (preflight paths, resume
  prerequisite, rollback, initialiser trigger) keys on the
  verification-wide predicate — plan design decision 3 is normative.

- **FR-5 — the evaluator contract (fresh context, running app).** The
  evaluator is invoked like a reviewer: a providers.toml provider command,
  executed once per landing gate, with
  - `CCT_CONFORMANCE_CRITERIA` — path to a JSON file of the frozen
    criteria `[ {fr, statement_sha, criterion} … ]`,
  - `CCT_CONFORMANCE_APP` — path to a JSON file carrying the frozen,
    evaluator-relevant app interface (`ready.url` when present — the
    base URL of the running app; nothing mutable),
  - `CCT_CONFORMANCE_RESULT` — path the evaluator MUST write verdicts to:
    `{ "criteria": [ {fr, statement_sha, criterion,
    verdict: "pass"|"fail", evidence} … ] }` — every verdict echoes its
    FULL frozen tuple,
  - `CCT_REVIEW_COST_FILE` — the adapter-written cost channel (FR-8),
  - cwd = the project; the app is already running (FR-6).
  The evaluator exercises the RUNNING APPLICATION, not the diff (#190 §6).
  The driver MUST ensure the result path is absent before invocation and
  require it newly produced (freshness). A result that is missing, stale,
  unparseable, schema-invalid, or that is not an EXACT identity multiset
  of the frozen criteria — any criterion missing, duplicated, phantom, or
  modified — MUST be treated as evaluator failure, never as a pass (fail
  closed; a criterion cannot pass by absence or by alteration).

- **FR-6 — driver-owned app lifecycle.** The driver, not the evaluator,
  starts and stops the application: `conformance.app` carries
  `{ "command": "...", "ready": { "url" | "command", "timeout_sec" },
  "stop_timeout_sec" }`. Start before the evaluator, prove readiness —
  the probe must succeed within its bound AND the spawned process group
  must still be alive at the moment it succeeds (a stale responder must
  not vouch for a dead launch); a failed probe is an evaluator-gate
  failure, fail closed — and stop the WHOLE process group afterwards with
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
  cap; `check_caps` runs after the gate. In-band cost text in the result
  file is never parsed as a measurement.

- **FR-9 — dispositions and resume.** Evaluator-gate failures use a
  dedicated reason (`conformance_gate`) with the C1 recovery contract:
  parks record `parked_head`; resume re-runs the gate; anything committed
  past the reviewed HEAD needs its review PASS first (the existing
  commit-bound recovery arm applies unchanged). An evaluator provider
  that is unhealthy AT THE GATE disposes `provider_unavailable` (its
  existing resume arm re-health-checks).

- **FR-10 — attended parity.** Attended runs with a conformance
  requirement enforce the same gate (park instead of terminate). Attended
  runs are NOT admission-checked (no admission exists there), so a
  missing/unhealthy evaluator surfaces at the gate, not earlier.

- **FR-11 — checkout integrity across the gate.** The landing verifier
  gate executes in the working checkout. Before verifier/app execution
  the tracked tree MUST be clean and the gate HEAD captured; after the
  evaluator finishes and the app is stopped, HEAD MUST be unchanged and
  the tracked tree clean. Any mutation of the checkout — by the app, a
  verifier command, or the evaluator — is a control-system failure:
  dispose `git_anomaly` naming the paths; the mutation MUST never reach
  the summary commit.

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
  healthy; each of {missing block, unresolvable provider, unhealthy
  provider} refuses with a named check. A yaml with no such mapping
  admits without the block, byte-identically to C1.
- **SC-2** An operator-supplied `conformance.required` is rejected by
  name; the accepted block round-trips the schema.
- **SC-3** The frozen contract pins the deterministic verifier set,
  evaluator, app contract, and criteria; editing `verification.yaml` or
  the config after initialisation changes nothing at the gate
  (asserted), and disk drift disposes exactly as C1's tamper rule does.
  A conformance-only run (no coverage block) freezes and takes a
  `-block` preflight path; resuming it without the frozen contract
  refuses (the lifecycle keys on the verification-wide predicate).
- **SC-4** The evaluator receives the criteria file, the frozen app
  interface (`CCT_CONFORMANCE_APP`), and the RUNNING app (readiness
  proven); its verdicts land in `verification-results.json` per FR; a
  failing criterion parks/terminates naming the FR; a result that is
  missing, stale, or not an exact identity multiset of the frozen
  criteria (missing, duplicated, phantom, or modified entries) fails
  closed (never pass-by-absence or -alteration).
- **SC-5** App lifecycle: ready-probe timeout fails the gate; a probe
  that succeeds while the spawned process group is dead fails the gate;
  after the gate no descendant of the app process group survives
  (asserted with a marker child, the cp_run_bounded pattern).
- **SC-6** A measured evaluator cost debits `cost_usd`; an unmetered one
  debits the estimate (flagged); in-band cost text is ignored; the cap
  parks when crossed at the gate (event order proven, C1 pattern).
- **SC-7** Attended and unattended dispositions: park with `parked_head`
  + commit-bound recovery resume; terminate with triage naming the FR.
- **SC-8** A frozen deterministic verifier whose command fails blocks
  landing (named in `verification-results.json`) even when the generic
  `test.command` gate is green — execution, not inference.
- **SC-9** A tracked-file mutation of the checkout during the gate (by
  the app or the evaluator) disposes `git_anomaly` naming the path, and
  the mutation never reaches the summary commit.
- **SC-10** All suites green; every SC regression verified to fail
  against the pre-change code (mutation runs recorded in the PR).
