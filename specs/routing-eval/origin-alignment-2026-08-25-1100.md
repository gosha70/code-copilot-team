# Origin Alignment Check — routing-eval

Date: 2026-08-25 11:00 (record opened)
Last revised: 2026-08-25 — child issues filed (#260 for E1, #261 for
E2) at the owner's direction; plan.md's origin block re-anchored from
the umbrella to #260. Rev-2 applied the owner's plan-review findings
(see "Plan review round 1" below). Scope unchanged from the verdict.
Revisions 3–5 applied plan-review rounds 2–4; the owner returned no
findings on rev-5 and approved the plan. plan.md moved to
`status: approved` on 2026-08-25, after PR #259 (increment D) merged as
`ed8873b`, unblocking E1's build entry. The bundle is committed on
`plan/routing-eval`, branched from that merge.
Trigger: rev-1 SDD bundle authored for increment E1 of #109 at the
owner's direction, immediately after increment D's PR (#259) was
opened. The owner split increment E into E1 (measurement substrate)
and E2 (analysis and recommendations) and directed that each get its
own child issue "so each merged PR fully closes its own scope". Child
issues #260 (E1) and #261 (E2) were filed the same day.

## Origin sources read

- #109 §12 Benchmark-driven evolution — the hybrid scenario arc
  (preferred Tier-1 → injected usage-limit → next Tier-1 → optional
  bounded Tier-2 → preferred recovery → Tier-1 reconciliation), the
  six task shapes plus explicit Tier-1-only negative controls, the
  primary measures, the secondary cost/time measures, and the
  five-condition calibration gate that keeps learned routing
  shadow-only.
- #109 §Delivery Plan Increment E — "Hybrid evaluation and adaptive
  recommendations": hybrid benchmark scenarios, routing-quality
  metrics, studio/session-analytics surface, shadow-mode routing
  recommendations, optional similarity/kNN only after calibration.
  E1 takes the first two; E2 takes the rest.
- #109 Acceptance §Evaluation and observability — all five
  checkboxes: decisions explainable from durable artifacts; tokens,
  costs, failed verifier commands, repair cycles, effective endpoint
  and effective model accurately recorded; artifacts exclude venvs,
  caches, bytecode and sensitive data; hybrid benchmarks run multiple
  trials; learned routing shadow-only until calibration.
- #109 §11 Telemetry and explainability — the per-event record E1's
  artifacts must satisfy, and the constraint that secret values,
  authorization headers, API keys, connector inventories, and
  sensitive absolute paths never enter analytics or public artifacts.
- #109 §Non-Goals — "Shipping learned or kNN routing before reliable
  benchmark evidence exists", which is precisely the gap E1 closes.
- The owner's E1/E2 split directive (2026-08-25), quoted in plan.md's
  origin references: E1 is "objectively verifiable", carries "no
  analytics UI or runtime recommendation behavior", and E2 "depend[s]
  on a stable evidence contract".
- specs/routing-recovery/ (D) and specs/routing-tier2-delegation/ (C)
  — the recovery/failback and provisional/reconciliation behaviour
  the hybrid scenario exercises.
- benchmarks/schema/{run-record,score,stats}.schema.json,
  benchmarks/presets/, benchmarks/adapters/ — the frozen harness
  contracts E1 extends rather than replaces.

## Working claim

Increment E1 supplies the evidence layer for the router increments
A–D built: a deterministic hybrid failover/recovery benchmark
scenario, #109's authoritative routing-quality metrics implemented
unchanged, and the control frame — always-best, always-cheapest, and a
hindsight oracle — plus cost-quality/Pareto reporting that makes a
router score interpretable (no AIQ scalar; see round 3, finding 2).
Artifacts are versioned, redacted, and reproducible. No analytics surface, no recommendation behaviour, no
learned routing, and no change to runtime routing.

## Mismatches / deviations from the origin sketch

1. **The control frame is an addition, not a substitution.** #109
   §12 names the primary measures but does not name baselines or an
   upper bound. Prior art in LLM routing evaluation (RouterBench and
   successors) is consistent that a router figure is uninterpretable
   without fixed-policy controls and an oracle bound, so E1 adds
   `always_best`, `always_cheapest`, and `oracle`, and reports `Q`,
   cost, and a Pareto frontier over the arms (no AIQ scalar — see
   round 3, finding 2). This *frames* #109's metrics; it does not
   reweight, combine, or replace any of them. Recorded as a deliberate extension for owner
   review.

2. **Increment E is split.** #109's delivery plan lists E as one
   increment. The owner directed an E1/E2 split on 2026-08-25 so each
   merged PR fully closes its own scope. E1's non-goals name every E2
   deliverable explicitly, so the union remains exactly #109's E.

3. **The oracle is derived, not executed.** #109 does not describe how
   an upper bound would be obtained. E1 derives the control arms from
   a `task × profile × trial` outcome matrix rather than executing
   four policies. Reuse of that matrix is fingerprint-gated — registry
   digest, preset digest (trial seeds and event stream), execution
   identity, task-set revision, tool/environment digest — so a
   registry edit invalidates it and forces a re-sweep; the saving is
   against re-executing the control policies, not against registry
   change. The oracle is labelled a hindsight bound and is never
   executable policy — consistent with #109's non-goal on speculative
   execution.

4. **Dependency on unmerged work.** E1's recovery and failback legs
   exercise increment D, whose PR (#259) is open and unmerged at the
   time this record was opened. tasks.md records the dependency; build
   entry is gated on that merge.

## Plan review round 1 (owner) — five findings, rev-2 applied

The owner's plan review returned three P1 and two P2 findings against
rev-1. All were verified against the repository before being applied;
none was accepted on report alone.

1. **[P1] No cost or telemetry evidence source.** Verified:
   `benchmarks/schema/stats.schema.json` fixes
   `cost_reporting.enabled` to `"const": false` and carries no cost
   amount; `score.schema.json` carries only `derived.failed_commands`
   and `scores.human_interventions` as integers. Rev-1's claim that
   cost came from `stats` was simply wrong, and `always_cheapest`, the
   cost plane, AIQ, and #260's accurate-telemetry acceptance were
   unimplementable as written. Resolved: FR-E1-2 and plan decision 4
   give E1 its own telemetry record with closed provenance
   `measured | estimated | unavailable`, verifier evidence references,
   repair signatures, and intervention records; `unavailable`
   propagates to `insufficient_evidence` rather than a default.

2. **[P1] Oracle and quality objective internally inconsistent.**
   Correct: rev-1 forbade combining the primary metrics while
   demanding one quality axis, one AIQ scalar, and a "per-row best"
   oracle, which is unsatisfiable; and a quality-maximising oracle is
   not guaranteed to cost no more than always-best. Resolved: FR-E1-5
   and plan decision 5 introduce a versioned `quality_fn: v1` used
   only for ordering and the oracle's per-task choice, with declared
   deterministic tie-breaks and the full metric vector always reported
   beside it. The oracle cost inequality is **dropped**; a separate
   `oracle_budget` arm carries the only meaningful cost ceiling.
   Fixed-baseline selection now reuses the selector's existing total
   order (priority ascending, then id lexical ascending).

3. **[P1] Matrix not comparison-valid.** Correct on all three counts.
   Resolved: FR-E1-6 and plan decision 3 make the matrix
   `task × profile × trial` with paired trial and event identity;
   FR-E1-7 restricts derived arms to per-task-independent measures and
   marks every sequence-dependent measure `not_applicable`; and matrix
   reuse is gated on an exact fingerprint over execution identity,
   task-set revision, tool/environment digest, and event-stream
   digest.

4. **[P2] No-runtime-change boundary unenforceable.** Correct — rev-1
   injected "at the backend-result boundary the router classifies"
   while claiming everything was downstream of execution. Resolved:
   plan decision 2 names the existing documented test-only seams
   (`CCT_SUPERVISOR_HARNESS_CMD` at cooldown-supervisor.sh:57,
   `CCT_ROUTING_PROBE_CMD` at routing-probe.sh:37), states that the
   benchmark supplies the *child output* and the unmodified classifier
   does its real work, and adds a diff guard asserting no production
   routing file is touched. The test strategy now states explicitly
   that passing suites alone does not prove runtime behaviour was
   untouched.

5. **[P2] Spec gate not green.** Verified: `validate-spec.sh
   --feature-id routing-eval` reported `spec.md missing required
   sections: Constraints`. Resolved: a Constraints section was added
   covering the no-runtime-change boundary, the injection seams, the
   frozen upstream contracts, fingerprint-gated reuse, bounded cost,
   and write-time redaction. The gate now reports 2 passed, 0 failed.

6. **[P3] Stale process text in this record.** Resolved above: the
   trigger paragraph no longer says the child issue is pending.

#260 is updated where it repeated the oracle-cost and single-sweep
matrix claims.

## Plan review round 2 (owner) — rev-3 applied

Round 2 found that rev-2 had answered the round-1 findings with prose
rather than definitions. The owner prescribed the closure: one
normative table defining each metric's raw source, formula,
aggregation, applicability and missing-value behaviour, followed by
exact definitions of `quality_fn` and every control selector. rev-3
applies exactly that.

1. **[P1] `quality_fn: v1` named but not defined.** Correct — rev-2
   gave purpose and tie-breaks but no numeric projection, leaving the
   central scoring policy to the implementer. Resolved: plan.md
   §quality_fn v1 now defines components (rows 1–8 only),
   normalization to `[0,1]` with direction, the fixed weight table
   summing to 1.0, weight renormalization when a component is dropped
   as `not_applicable`, withholding `Q` entirely on any
   `insufficient_evidence` component, and the full tie-break sequence.
   The round-2 sub-finding is also fixed: reconciliation rework is no
   longer a tie-break, because it is `not_applicable` for derived arms
   and would make arms incomparable.

2. **[P1] Telemetry contract could not produce all authoritative
   metrics.** Correct. Resolved: plan.md §Metric contract enumerates
   all thirteen measures with raw evidence, per-cell formula,
   aggregation, applicable arms, and missing-value behaviour; T1 now
   requires the schema to carry every source field it names —
   baselines for lint/type, `quality_gates.coverage`,
   `quality_gates.security.findings_by_severity`, `scope_violations[]`
   (reusing increment C's file-scope enforcement),
   `tier2.{delegated, delegated_lines, reconciliation_diff_lines}`,
   and `rollbacks[]` — with a per-metric test asserting presence. A
   metric not in the table is not reported.

3. **[P1] Reuse fingerprint did not enforce its stated identity.**
   Correct: rev-2 claimed a registry edit invalidates reuse while
   omitting the registry digest, and omitted trial-seed identity.
   Resolved: the fingerprint is now a closed five-component list —
   `registry_digest`, `preset_digest` (covering trial count, seeds,
   event stream, arm set), `execution_identity`, `task_set_revision`,
   `toolchain_digest` — all schema-required, with a mismatch test per
   component.

4. **[P1] Control derivation ambiguous over the trial matrix.**
   Correct on all four sub-points. Resolved: plan.md §Control
   selectors states that a control is a per-task selection under a
   fixed rule rather than a literal matrix column (handling per-task
   eligibility); `always_cheapest` selects on mean cost across a
   task's trials using `measured` provenance only, with estimated and
   measured explicitly non-comparable and insufficiency rather than
   silent fallback; and `oracle` chooses per `(task, trial)` — the
   true hindsight bound — rather than after aggregating trials.

5. **[P3] Stale consistency references.** Resolved: this record's
   deviation 3 no longer describes an `N_tasks × N_profiles` sweep or
   claims a registry change costs one router run; plan.md decision 6
   now cites FR-E1-8 and decision 9 now cites decision 6.

## Plan review round 3 (owner) — rev-4 applied

Round 3 confirmed rounds 1–2 were closed correctly and found five
remaining gaps, all in the cost and reporting path. The owner
prescribed a single "Cost and reporting contract" section plus a
spec.md sync; rev-4 applies exactly that.

1. **[P1] Cost field had storage but no producer.** Verified:
   `BackendResult` (`scripts/benchmark_runner/contracts.py`) carries
   token counts but no cost, so with `always_cheapest` requiring cost
   and the control-set gate mandatory, no current backend could
   produce a report. Resolved: plan.md §Cost and reporting contract
   names the producers — `measured` from the backend's own reported
   `total_cost_usd` (the in-tree precedent is `rb_measured_cost` in
   `scripts/lib/routing-probe.sh`, which already reads exactly that
   field), `estimated` from tokens × a versioned `price_table: v1`,
   `unavailable` otherwise — and T1 extends `BackendResult` with
   `cost_usd` and `cost_provenance`. The plane's mixing gap is closed
   by **provenance homogeneity**: a comparison declares one
   `cost_basis`, and every cell used for cost must satisfy it, for
   selection *and* for the plane, frontier and budget arm alike.

2. **[P1] AIQ required but never defined.** Correct. Resolved by
   removing it: an AIQ-family scalar integrates a cost-quality
   *curve*, which presupposes a tunable cost knob tracing a family of
   operating points. The CCT router is a single operating point under
   a given registry, so an "AIQ" here would be an invented ratio
   rather than the published metric. E1 now reports `Q`, cost under
   the declared basis, and the Pareto frontier — nothing else.
   Defining AIQ becomes meaningful only if a tunable knob is ever
   introduced, and is then later work.

3. **[P1] `oracle_budget` mixed two ceiling semantics.** Correct — a
   per-cell filter does not bound a summed arm cost. Resolved: the
   ceiling is declared **per-cell and only per-cell**, the test
   asserts it for every selected cell, and no aggregate-cost invariant
   is asserted. Global-budget allocation is explicitly out of scope
   (it is a knapsack problem, not a filter, and #109 does not ask for
   one).

4. **[P2] Component mask ambiguous during oracle selection.**
   Correct — per-cell mask derivation would let different cells score
   under different weightings. Resolved: the mask and its renormalized
   weights are computed **once** over the complete report matrix
   before any control selection, and that single mask is used
   identically everywhere including the oracle's per-cell choice.
   Per-cell derivation is forbidden.

5. **[P2] spec.md stated pre-revision contracts.** Correct. Resolved:
   FR-E1-3 now states the declared-`cost_basis` rule and per-`(task,
   trial)` oracle selection; FR-E1-5 says per-cell rather than
   per-task; FR-E1-8 drops AIQ and states the homogeneity rule; and
   the Constraints fingerprint now lists all five components including
   `registry_digest` and `preset_digest`.

## Plan review round 4 (owner) — rev-5 applied

Round 4 confirmed no architectural issue remains and listed bounded
consistency and test-ownership corrections. rev-5 applies them, plus
one conflict found while verifying finding 2.

1. **[P1] `always_cheapest` carried two conflicting rules.** Correct —
   the §Control selectors paragraph still demanded measured-only cost
   after §Cost and reporting contract superseded it with provenance
   homogeneity. Resolved: the duplicated paragraph is deleted and the
   selector now defers explicitly, adding no provenance rule of its
   own.

2. **[P2] Measured-cost surface not pinned — and a constraint conflict
   found while pinning it.** Verified:
   `test_no_dollar_cost_in_backend_metadata`
   (`scripts/benchmark_runner/tests/test_claude_code_backend.py`)
   asserts `total_cost_usd` must NOT reach `backend_metadata`, citing
   a standing constraint. Tracing it found
   `specs/benchmark-harness/spec.md` § Constraints: dollar-cost
   reporting is "permanently out of scope until billing-correlation is
   solved across providers; no schema slot for cost estimation is
   added." Rev-4's proposal to add `cost_usd` to `BackendResult` would
   have silently reversed that cross-spec constraint.

   Resolved without reversing it: E1 adds no cost to `BackendResult`,
   `backend_metadata`, or any shared harness schema. The
   `routing_hybrid` scenario reads `total_cost_usd` from the backend
   transcript into E1's own routing-eval-owned record, which declares
   its `cost_basis`. The harness constraint, its absent schema slot,
   and its guarding test all remain intact and unmodified. The file
   map now names `benchmarks/report/cost_reader.py` instead of
   `contracts.py`, and T1 carries the three required regressions
   (valid non-negative value becomes `measured`; invalid or negative
   does not; missing falls through to the versioned estimator or
   `unavailable`) plus an assertion that `backend_metadata` still
   carries no cost.

3. **[P2] #260 described the superseded contract.** Resolved: the
   issue body is synchronized with rev-5 — AIQ removed, per-`(task,
   trial)` oracle, five-component fingerprint, per-cell budget
   semantics, global component mask, and the cost-ownership boundary.

4. **[P3] Stale local summaries.** Resolved: the test strategy now
   lists all five fingerprint components with one mismatch test each
   and adds the cost-provenance regressions; this record's working
   claim and deviation 1 no longer promise an AIQ scalar. Descriptions
   inside rounds 1–3 retain AIQ deliberately, as history of what those
   rounds addressed.

## T1 build audit (owner review) — seven findings, all applied

The owner reviewed the first T1 build before commit and found that the
52 passing tests did not enforce the principal contracts. All findings
verified in-tree (the validator blindness was reproduced: a mixed
candidates+arms config and an empty fingerprint both returned zero
errors) and resolved:

1. **Parser enforcement.** `compare.py:_validate` now refuses a config
   declaring both `candidates` and `arms`/`scenario` with its own
   error, and refuses scenario-only configs with a pointer to the
   routing-eval path instead of silently running them as candidate
   comparisons. `routing_eval/scenario_config.py` is the executable
   validator for the scenario shape (closed arm kinds, cct_router
   requires a registry, cost_basis pattern, trial_seeds length ==
   trials, budget ceiling if-and-only-if an oracle_budget arm, event
   stream shapes); the T4 driver will load configs only through it.
2. **Tests prove rejection.** test_routing_eval_schemas.py ships its
   own validator covering $ref, oneOf, not, const, pattern, minLength,
   minItems (with self-checks), and asserts the negatives: mixed
   configs, empty fingerprints, empty cells, bad cost pairings, and
   evidence-free verifier rows are all REJECTED, by schema and by the
   executable parsers. Side-catch: the stricter validator exposed that
   `cross-language-mini.json` has shipped with one candidate since
   dfc85c7, violating the schema's own minItems:2 — pinned as a known
   pre-existing violation (fixing a shipped preset is outside E1).
3. **measured_cost reads the transcript stream.** It now mirrors
   rb_measured_cost's selection rule: normalize JSON/JSONL, take the
   LAST type:"result" record (or the single untyped object), and only
   then validate the number. An assistant record carrying a
   total_cost_usd key can no longer forge a measured cost.
4. **Estimator strictness.** Negative/non-finite/boolean counts and
   rates refuse the whole estimate; input AND output must both be
   priced; consumed cache tokens without a cache rate refuse rather
   than understate. Cost's documented invariants are enforced in
   __post_init__, so `Cost(None, "measured")` cannot exist and
   satisfies() never sees a degenerate value.
5. **Raw executions vs derived arms.** routing-run's `arm` field is
   replaced by `mode` (profile_sweep | cct_router) + `profile_id`,
   with a oneOf pairing: a sweep record names its fixed profile, a
   router record fixes none. The four derived arms are deliberately
   unrepresentable as executions — a record claiming one is a
   fabrication and fails validation.
6. **Invariants encoded, not described.** Cost/provenance pairing is a
   oneOf in both schemas; verifier evidence_ref is required and a
   non-empty string; execution_identity requires all seven keys; the
   matrix requires trial_seeds and cost_basis.
7. **Stale gate.** This record refresh clears it.

## T1 build audit round 2 (owner) — five findings, all applied

The owner's second pre-commit audit found the executable and persisted
contracts still fail-open in five places. Each was reproduced in-tree
before fixing (a single-cct_router-arm config with a typo'd
`trial_seedz` key and no cost_basis validated cleanly), then closed:

1. **Complete control set at load time.** scenario_config now requires
   each of `always_best`, `always_cheapest`, `oracle`, `cct_router`
   exactly once (FR-E1-3), with `oracle_budget` the only optional kind
   (at most once), and `cost_basis` is mandatory. The schema's `arms`
   floor rose to minItems 4, with the composition rule enforced by the
   parser the T4 driver loads through.
2. **Closed keys + finite numbers.** Unknown top-level, arm, and event
   keys are refused (`trial_seedz`, `regsitry`, `outcoem` all reject);
   the budget ceiling refuses NaN/infinity/booleans.
3. **Evidence containers are required.** routing-run now requires every
   evidence container — a writer records an empty array, explicit
   nulls, or an insufficient_evidence entry, never an absent key — so
   missing evidence is explicit rather than indistinguishable from an
   incomplete writer. routing_decision requires its full FR-E1-10
   vocabulary including the new `provisional_outcome` field.
4. **Estimated cells keep their table identity.** Matrix cell cost
   gains a required `estimator`: estimated cells must name their price
   table (a versionless estimated cell rejects), measured/unavailable
   cells carry null — the artifact can now PROVE its costs came from
   the declared basis table.
5. **Reproducibility + robustness.** `Cost` refuses empty estimator
   inputs (an estimate that cannot be recomputed is not evidence);
   malformed price-table roots yield `unavailable` instead of an
   AttributeError, and load_price_table raises a named error on a
   non-object root.

## T1 build audit round 3 (owner) — three findings, all applied

The owner's third pre-commit audit found the persisted/config contracts
still fail-open at three seams. All three resolved:

1. **Axes own their fields, both in schema and in code.** Each
   compare-config oneOf branch now requires its own fields and forbids
   the other axis's (candidate branch forbids arms/scenario/cost_basis/
   trials/trial_seeds/event_stream/budget_ceiling_usd; scenario branch
   requires cost_basis and forbids candidates/runs/
   attempt_timeout_seconds). compare.py additionally refuses
   scenario-only keys on a candidate config even when scenario/arms are
   absent — a cost_basis the author clearly intended is never silently
   ignored. The test validator gained anyOf support (with self-checks)
   so these rejections are proven, not described.
2. **Evidence containers cannot be hollow.** The owner's reproduction
   (injected_events [{}], considered [{}], empty baseline/
   quality_gates/tier2, rollbacks [{}], insufficient_evidence {}) now
   fails per container: injected events share the preset's closed
   event shape; considered candidates require id/verdict/reason;
   baseline, quality_gates (through findings_by_severity), and tier2
   require their fields (explicit nulls, never absent keys); rollbacks
   require kind and detail; insufficient_evidence is a keyed map whose
   entries REQUIRE a reason, with an empty object rejected because it
   asserts neither sufficiency nor insufficiency.
3. **Estimator inputs are recomputable, not merely non-empty.**
   The inputs shape is closed: input and output buckets required,
   cache buckets optional, every present bucket pairing a valid token
   count with a valid rate_per_million; unknown buckets refuse. A
   round-trip test proves whatever estimate_cost emits reconstructs to
   the same value.

## T1 build audit round 4 (owner) — one finding, applied

The last open seam in the cost-reproducibility contract: an estimated
cost was not bound to its recorded inputs. Both halves of the owner's
reproduction are closed:

- **Schema**: `$defs/estimate_inputs` pins the closed shape (input and
  output buckets required, cache optional, every bucket pairing tokens
  with rate_per_million), and the estimated branch of the cost oneOf
  references it — `inputs: {"input": {"tokens": 1}}` no longer
  validates.
- **Construction**: `Cost.__post_init__` recomputes the total from the
  recorded inputs and refuses a value that does not equal it
  (isclose, rel 1e-9). A structurally valid understated cost — the
  owner reproduced value=1.0 over inputs recomputing to ~0.000002 —
  can no longer exist to win `always_cheapest`.

## T2 build audit round 1 (owner) — four findings, all applied

The owner's pre-commit audit of T2 found the replay engine could not
satisfy the real probe contract and was fail-open on scheduling,
concurrency, and quoting. All four resolved, each now covered by a
regression the original suite lacked:

1. **The probe replay satisfies the REAL rb_probe.** A declared
   success event is now pass-mode (answered from the prompt) instead
   of the canned harness result that failed the nonce; the expected-
   line extraction matches both rb_prompt forms (the tool-required
   prompt says "Then reply...", lowercase); and when the prompt names
   a tool command the replay RUNS that exact command, which writes the
   marker to CCT_PROBE_TOOL_FILE. Four end-to-end tests drive the
   unmodified rb_probe: inference-only pass, declared-success pass,
   tool-required pass (proving the tool canary landed), and an
   injected auth failure reaching probe_fail through the real
   classifier.
2. **at_task_index has a boundary.** events_for_task() is the
   scheduling filter: an event declared for task 5 never reaches task
   0's replay, within-task order is declaration order, and
   materialize_replay documents that it consumes an already-scheduled
   invocation stream. The T4 driver materializes one replay per task
   through this filter.
3. **The event index is claimed atomically.** The unlocked
   read-modify-write counter (reproduced losing 16 of 40 concurrent
   increments) is replaced by mkdir-based claims — each invocation
   owns exactly one index. A 40-way concurrent test asserts all 30
   events delivered exactly once plus exactly 10 defaults.
4. **Paths are quoted.** The script resolves its directory from $0 and
   the returned command is shlex-quoted; a replay directory containing
   spaces now works and is tested.

## T2 build audit round 2 (owner) — two findings, all applied

Round 2 found two remaining fail-open/fail-unsafe paths in the replay:

1. **Missing declared evidence fails closed.** The materialization now
   records the stream length, and the script distinguishes four cases
   in order: explicit pass mode (the .mode file is READ, not inferred
   from absence); complete .out+.rc evidence; a declared index with
   missing or corrupt evidence — exit 70 with a stderr message, never
   success and never a clean provider failure (the owner's repro:
   deleting an auth-failure transcript had become a nonce pass); and
   past-the-stream default. Regressions cover a deleted .out, a
   deleted .rc, and a declared mid-stream pass.
2. **Prompt text is never executed.** The tool leg validates the
   request against rb_prompt's CLOSED canary shape — the exact string
   `printf %s CCT_TOOL_OK > $CCT_PROBE_TOOL_FILE` with the path equal
   to the exported env var — and writes the marker itself. Any other
   tool request exits 70 without execution. The owner's injection
   repro (a `touch` in the expected prompt shape) is now a regression
   asserting the file is NOT created; the legitimate canary shape is
   asserted to write the marker and pass, and the end-to-end
   rb_probe tool test still passes, proving the validated shape is
   exactly what the real probe emits.

## T2 build audit round 3 (owner) — three findings, all applied

Round 3 found the replay's integrity boundaries still open:

1. **Re-materialization defines the complete stream.** Materialization
   now cleans every owned artifact (event files, defaults,
   stream-count, manifest, claims) before writing, and the script
   consults event files ONLY inside `n < count`. The owner's repro —
   two events, re-materialize one, stale second failure replayed past
   stream-count=1 — is a regression asserting the stale event never
   fires and index 1 gets the default.
2. **Evidence is digest-bound, not merely readable.** Every sidecar's
   sha256 is recorded in a manifest, and the manifest's own digest is
   EMBEDDED in the generated script, so a flipped .rc, an edited
   transcript, an altered stream-count, and even a self-consistently
   recomputed manifest over tampered evidence all fail closed (exit
   70) — each is a regression. stream-count and .rc are additionally
   syntax-validated as numbers.
3. **The seam vocabulary is closed.** `REPLAY_SEAMS = ("harness",
   "probe")`; anything else is refused by name at entry, so a typo'd
   seam can never silently fall into harness semantics and recreate
   the canned-reply nonce failure.

## T3 build audit round 1 (owner) — HOLD on one invariant, applied

The owner approved the selector semantics and held T3 on one missing
invariant: a persisted matrix must PROVE exact Cartesian coverage, not
merely schema validity — a matrix that lost one expensive trial cell
would let always_cheapest win on incomplete evidence, and a vanished
oracle candidate silently lowers the hindsight bound.

Resolved with two structural additions and one shared validator:

- The matrix now DECLARES its task list (`tasks`, schema-required):
  without it, a fully vanished task is undetectable after load.
- Every cell carries its `seed` (schema-required), making the cell's
  canonical identity (task_id, profile_id, trial, seed) and the
  trial-index/seed pairing verifiable after load.
- `verify_matrix()` re-establishes the invariant — exactly one cell
  per declared task x declared profile (the fingerprint's execution
  identity) x declared (trial, seed); no duplicates; no undeclared
  cells; seed pairing exact; eligibility never removes the cell
  requirement. `build_matrix` runs it before returning and EVERY
  selector runs it before selecting.

Regressions cover each required mutation: the owner's bias fixture
(alpha $1/$1/$9 vs beta $2/$2/$2 — the complete matrix picks beta, the
pruned one REFUSES rather than letting alpha win at $1 mean); a removed
ineligible cell (explicit ineligibility never becomes silence); a
duplicated identity; a trial carrying another trial's seed; and a
persistence round-trip whose post-load mutation refuses.

## Verdict

Verdict: aligned
Confidence: high

Scope is a strict subset of #109 increment E, with the E1/E2 boundary
drawn by the owner. The single substantive extension beyond the origin
text — the control/oracle frame — is additive to #109's authoritative
metric set and is recorded above for owner review at the plan gate.
