---
spec_mode: full
feature_id: routing-eval
status: approved
date: 2026-08-25
risk_category: integration
justification: >
  Adds a new comparison axis to the benchmark harness (routing policy
  rather than fixed backend/model candidate), a new durable artifact
  schema, and a scenario that drives the live supervisor through
  injected provider events. Integration risk across the benchmark
  runner, the routing registry/state contracts increments A-D froze,
  and the artifact redaction rules — but it adds no runtime execution
  authority and changes no routing behaviour.
origin:
  type: issue
  issue: 260
  parent: 109
  references:
    - "#109 §12 Benchmark-driven evolution — the hybrid scenario arc, the six task shapes, the primary measures, and the shadow-mode/kNN calibration gate"
    - "#109 §Delivery Plan Increment E — hybrid benchmark scenarios, routing-quality metrics, analytics surface, shadow-mode recommendations (E1 takes the first two)"
    - "#109 Acceptance §Evaluation and observability — all five checkboxes"
    - "#109 §11 Telemetry and explainability — the per-event record E1's artifacts must satisfy, and the secret-redaction constraint"
    - "The owner's E1/E2 split directive (2026-08-25): E1 is the measurement substrate, objectively verifiable, no analytics UI and no runtime recommendation behaviour; E2 depends on a stable evidence contract"
    - "benchmarks/schema/{run-record,score,stats}.schema.json — the frozen record contracts E1 extends rather than replaces"
    - "specs/routing-recovery/ (D), specs/routing-tier2-delegation/ (C) — the recovery/failback and provisional/reconciliation behaviour the scenario exercises"
  origin_claim: |
    #109 increment E, first half: supply the evidence layer for the
    router A-D built — a deterministic hybrid failover/recovery
    benchmark scenario, #109's authoritative routing-quality metrics,
    and the control frame (always-best, always-cheapest, oracle) plus
    cost-quality/Pareto reporting that makes a router score
    interpretable. Versioned reproducible artifacts, no analytics
    surface, no recommendation behaviour, no learned routing.
  note: |
    Child issue #260 filed 2026-08-25 at the owner's direction to split
    increment E into E1/E2 with a separate issue each. The sibling E2
    issue is #261. The increment-D gate is satisfied: PR #259 merged
    as `ed8873b` on 2026-08-25.
---

# Plan: Hybrid routing evaluation — measurement substrate (E1 of #109)

`spec.md` states the requirements; THIS file's decisions are the
normative implementation contract. The A–D routing surfaces and the
benchmark harness's existing record schemas are consumed **frozen** —
where E1 extends them it does so visibly, with its own regressions.

## Decisions

1. **The comparison unit is a routing policy, and it is a new preset
   kind — not a new candidate shape.** Today a preset lists
   `candidates[]`, each fixing a backend and model. E1 adds
   `arms[]` under a `scenario: "hybrid-routing"` preset. Overloading
   `candidates[]` would make every existing preset ambiguous; a
   distinct key keeps the old contract byte-compatible and lets the
   validator reject a preset that mixes the two.

2. **Injection drives the existing test-only seams; production
   routing code is untouched.** The named seams are
   `CCT_SUPERVISOR_HARNESS_CMD` (documented at
   `scripts/cooldown-supervisor.sh:57` as "override the child command
   (a mock harness)") and `CCT_ROUTING_PROBE_CMD`
   (`scripts/lib/routing-probe.sh:37`, "Test seam"). The benchmark
   supplies the **child's output** through those seams — a transcript
   shaped like a usage-limit response, with a stated reset instant —
   and the real, unmodified classifier then does its real work on it.
   E1 never injects at, patches, or bypasses the classification
   boundary, and modifying any production routing file is out of
   scope for this increment: a diff that touches one is a defect, not
   a design choice. The event stream is preset-owned, recorded in the
   artifact, and part of the preset digest, so two runs of one preset
   see the same events in the same order. No leg depends on
   wall-clock timing for correctness.

3. **The matrix is `task × profile × trial`, and its reuse is
   fingerprint-gated.** This is the decision that makes E1 affordable,
   with three constraints that make it *valid*:

   - **Trials are a dimension, not an average.** One cell per
     task/profile cannot support FR-E1-6's multiple trials. Cells are
     keyed `(task, profile, trial)`, and trial seeds and injected-event
     identity are paired across arms so every arm sees the same trial
     under the same conditions.
   - **Only independent measures may be derived.** Control arms come
     from independent cells, so they carry only per-task-independent
     measures: verifier outcome, regressions, cost, elapsed time.
     Sequence-dependent measures — reconciliation rework ratio, Tier-2
     accepted unchanged, failback behaviour, switch-induced rollbacks —
     exist only along a stateful run and are reported
     `not_applicable` for derived arms, measured only for
     `cct_router`.
   - **Reuse requires an exact match on every component of the
     fingerprint**, which is the closed list:
     1. `registry_digest` — the routing registry as parsed. Any
        registry edit invalidates reuse.
     2. `preset_digest` — covers trial count, trial seeds, the
        injected event stream, and the arm set. Changed seeds cannot
        reuse cells keyed by the same trial index.
     3. `execution_identity` per profile — id, backend, provider,
        requested model, effective model, tool profile, sanitized
        endpoint identity.
     4. `task_set_revision` — the pinned snapshot revision.
     5. `toolchain_digest` — tool and environment fingerprint.

     A mismatch in any component refuses reuse; stale cells are never
     silently carried forward. The schema requires all five, and a
     mismatch test exists per component.

   Control arms are derived from a matching matrix exactly as
   §Control selectors defines; only `cct_router` executes live,
   because its choices depend on the event stream and real failure
   classification.

4. **E1 owns its telemetry record, because the evidence does not
   exist upstream.** This was verified, not assumed:
   `benchmarks/schema/stats.schema.json` fixes
   `cost_reporting.enabled` to `"const": false` and carries **no cost
   amount** at all; `score.schema.json` carries only
   `derived.failed_commands` (an integer) and
   `scores.human_interventions` (an integer) — not the commands, the
   evidence, or the interventions. Sourcing cost or verifier evidence
   from them, as an earlier draft of this plan did, is impossible.

   The routing-run record therefore carries per attempt:
   - `tokens.{input, output, cache_read, cache_write}`;
   - `cost.{value, provenance, estimator, inputs}` where provenance is
     the closed set `measured | estimated | unavailable`, and
     `estimator`/`inputs` are required whenever it is `estimated`;
   - `verifiers[]` — each execution's command, exit status, and an
     addressable evidence reference (not a count);
   - `repair_cycles[]` with repeated-failure signatures;
   - `interventions[]` — records, not a count.

   Quality outcomes still come from `score.schema.json`; elapsed time
   still comes from `stats.schema.json`. Only what is genuinely
   missing is added. A measure whose provenance is `unavailable`
   propagates as `insufficient_evidence` and is never defaulted to
   zero — which is what makes `always_cheapest` and the cost axis
   honest rather than fabricated.

5. **`quality_fn: v1` orders arms; it does not redefine the metrics.**
   An earlier draft forbade combining the primary metrics while also
   demanding one quality axis and a "per-row best" oracle — which is not satisfiable, because ordering a vector
   requires a projection. The resolution is to make the projection
   explicit, versioned, and clearly subordinate:

   - `quality_fn` is a named, versioned function over the primary
     metric vector, used **only** for ranking arms and for the
     oracle's per-cell choice. §quality_fn v1 defines it numerically;
     nothing about the scoring policy is left to the implementer.
   - Every report states which `quality_fn` version produced its
     ordering and carries the full metric vector beside it. The
     scalar never appears without the vector.
   - **It admits only metrics applicable to every arm being
     compared.** Sequence-dependent measures are `not_applicable` for
     derived arms, so including one would make the arms incomparable —
     which is why reconciliation rework is *not* a `quality_fn`
     component or tie-break, despite an earlier draft using it as one.
   - **The oracle bounds quality, not cost.** The earlier assertion
     that oracle cost is `<=` always-best's is dropped: a
     quality-maximising choice may legitimately cost more. The only
     invariant asserted is that oracle quality under the declared
     `quality_fn` is `>=` every other arm on the same matrix. A
     separate, explicitly-labelled `oracle_budget` arm — best quality
     subject to a stated cost ceiling — may be reported alongside, and
     is the only arm for which a cost inequality is meaningful.

6. **A router score without a complete control set is a hard error.**
   The reporter refuses to emit a `cct_router` figure unless
   `always_best`, `always_cheapest`, and `oracle` are all present for
   the same task set, trial seeds, and event stream. This is FR-E1-8
   enforced in code, not documented as guidance — an uncontrolled routing number
   is the specific failure mode this increment exists to prevent.

7. **New artifact: `routing-run.schema.json`, versioned from day
   one.** It carries `schema_version`, preset digest, registry digest,
   pinned task-set revision, the injected event stream, and per-task
   routing decisions in the vocabulary `explain` already speaks
   (candidates considered with per-candidate verdict and reason,
   selected profile, requested and effective model, sanitized upstream
   endpoint, failure classification, provisional/reconciliation
   outcome). The three existing schemas are extended by reference, not
   edited.

8. **Redaction is a property of the writer, not the reader.** Secret
   values, authorization headers, API keys, connector inventories, and
   sensitive absolute paths are scrubbed at the point the record is
   written, so a leaked artifact cannot contain them regardless of who
   reads it. Virtual environments, caches, bytecode, and generated
   runtime noise are excluded from the changed-file measure by the
   same writer.

9. **Insufficiency is a first-class outcome.** An arm that cannot run
   records `insufficient_evidence` with a reason and is carried
   through to the report as such. It is never rendered as zero, never
   silently dropped from the Pareto set, and never allowed to satisfy
   decision 6's control requirement.

10. **E1 adds no runtime authority.** No new key the router reads at
   execution time, no new policy surface, no code path that changes a
   routing decision. Everything E1 adds is downstream of execution.
   This is what makes E1 independently verifiable and what lets E2
   depend on it as a stable evidence contract.

## Metric contract

Normative. Every metric #109 names, its raw evidence, its formula, how
it aggregates, which arms it applies to, and what happens when the
evidence is absent. `RR` = the new routing-run record, `SC` =
`score.schema.json`, `ST` = `stats.schema.json`. **A metric not in this
table is not reported.**

Cell = `(task, profile, trial)`. Unless stated otherwise, a metric is
computed per cell, averaged over trials to a per-task value, then
averaged over tasks with equal task weight to the arm value.

| # | Metric | Raw evidence | Per-cell formula | Aggregation | Arms | Missing evidence |
|---|---|---|---|---|---|---|
| 1 | Final verifier pass rate | `SC.result` | `1` if `result == "pass"` else `0` | mean over trials → mean over tasks | all | `insufficient_evidence` |
| 2 | Lint regression | `SC.scores.lint_passed`, `RR.baseline.lint_passed` | `1` if baseline passed and post-run did not | mean → mean | all | component excluded, arm flagged |
| 3 | Type regression | `SC.scores.typecheck_passed`, `RR.baseline.typecheck_passed` | as row 2 | mean → mean | all | as row 2 |
| 4 | Coverage regression | `RR.quality_gates.coverage.{before, after}` (NEW) | `1` if `after < before - tol`, `tol` preset-declared | mean → mean | all | as row 2 |
| 5 | Security regression | `RR.quality_gates.security.findings_by_severity.{before, after}` (NEW) | `1` if any severity count increased | mean → mean | all | as row 2 |
| 6 | Architecture / scope violation | `RR.scope_violations[]` (NEW) — files changed outside the task packet's declared file scope, reusing increment C's exact file-scope enforcement | `1` if `len > 0` | mean → mean | all | as row 2 |
| 7 | Repeated repair cycles | `RR.repair_cycles[]` with `signature` | `1` if any signature occurs more than once | mean → mean | all | as row 2 |
| 8 | Human intervention | `RR.interventions[]` | `1` if `len > 0` | mean → mean | all | as row 2 |
| 9 | Tier-2 accepted unchanged | `RR.tier2.{delegated, reconciliation_diff_lines}` (NEW) | over cells where `delegated`: `1` if `reconciliation_diff_lines == 0` | sum numerator / sum denominator over delegated cells only | `cct_router` only | `not_applicable` for derived arms |
| 10 | Tier-1 reconciliation rework ratio | `RR.tier2.{delegated_lines, reconciliation_diff_lines}` (NEW) | ratio numerator `reconciliation_diff_lines`, denominator `delegated_lines` | sum numerator / sum denominator | `cct_router` only | `not_applicable` for derived arms |
| 11 | Rollbacks | `RR.rollbacks[]` (NEW) — switch-induced revert events | count | sum over cells | `cct_router` only | `not_applicable` for derived arms |
| 12 | Cost (secondary) | `RR.cost.{value, provenance}` | `value` | mean over trials → sum over tasks | all | `unavailable` → `insufficient_evidence`, never `0` |
| 13 | Elapsed (secondary) | `ST.elapsed_seconds` | value | mean → sum | all | `insufficient_evidence` |

Rows 9–11 are the sequence-dependent measures: they exist only along a
stateful run, are `not_applicable` for every derived arm, and are
therefore excluded from `quality_fn` (see below).

Ratio metrics (9, 10) aggregate as **sum of numerators over sum of
denominators**, never as a mean of per-cell ratios. A denominator of
zero yields `not_applicable`, not zero.

## quality_fn v1

Normative. A declared reporting projection used for exactly two
purposes: ranking arms, and the oracle's per-cell choice. It is
reported only beside the full metric vector of §Metric contract, and
every report names the version that produced its ordering.

**Components.** Only metrics applicable to *every* arm in the
comparison — rows 1–8. Rows 9–11 are excluded because derived arms
cannot carry them; including one would make arms incomparable. Cost
(12) is excluded because it is the other axis of the cost-quality
plane.

**Normalization.** Each component maps to `[0, 1]` with higher always
better. Row 1 is already a rate and is used directly. Rows 2–8 are
adverse rates `r ∈ [0, 1]`; each contributes `1 - r`.

**Aggregation.** A weighted sum over the normalized components, with
weights fixed at v1 and summing to `1.0`:

| Component | Weight |
|---|---|
| Verifier pass rate (1) | 0.50 |
| Lint regression (2) | 0.075 |
| Type regression (3) | 0.075 |
| Coverage regression (4) | 0.075 |
| Security regression (5) | 0.075 |
| Architecture / scope violation (6) | 0.10 |
| Repeated repair cycles (7) | 0.05 |
| Human intervention (8) | 0.05 |

`Q = Σ (weight_i × normalized_i)`, yielding `Q ∈ [0, 1]`. This is the
quality axis of the cost-quality plane. It is the only quality scalar
E1 emits (see §Cost and reporting contract on AIQ).

**Not-applicable and unavailable handling.**
- A component that is `not_applicable` for *any* arm in the comparison
  is dropped from *every* arm's `Q`, and the remaining weights are
  renormalized to sum to `1.0`. The report lists which components were
  included. This keeps arms comparable by construction.
- A component that is `insufficient_evidence` for any arm withholds
  `Q` entirely for the whole comparison — it is never imputed,
  defaulted, or dropped. `Q` is not "best effort".

**Tie-breaking.** When two arms' `Q` differ by less than `1e-9`, order
by, in sequence: verifier pass rate descending; total regression count
(rows 2–5) ascending; scope violations (6) ascending; repeated repair
cycles (7) ascending; interventions (8) ascending; cost ascending; arm
id lexical ascending. Reconciliation rework is deliberately **not** a
tie-break — it is `not_applicable` for derived arms. The final key
guarantees a total order, so an ordering is never an artifact of
iteration order.

## Control selectors

Normative. All three controls are derived from a fingerprint-matching
matrix. **A control is not a literal matrix column**: eligibility
varies per task, so each control is a per-task selection under a fixed,
declared rule.

Let `eligible(p, t)` be true when profile `p` is eligible for task `t`
under the registry and the task's route class — the same predicate the
selector uses, read from the registry, never re-implemented.

**`always_best`.** For each task `t`, choose `p` among `eligible(p, t)`
with the highest capability tier; ties by priority ascending, then
profile id lexical ascending — the selector's existing total order. The
arm's cells are that profile's cells for `t` across all trials. Tasks
with no eligible profile are `insufficient_evidence`.

**`always_cheapest`.** For each task `t`, choose `p` among
`eligible(p, t)` minimizing the **mean cost across that task's trials**,
using only cells satisfying the declared `cost_basis`. Ties by profile
id lexical ascending.
If any eligible profile for `t` has no cell meeting the declared
`cost_basis`, task `t` is `insufficient_evidence` for this arm.
§Cost and reporting contract is authoritative on provenance; this
selector adds no provenance rule of its own.

**`oracle`.** Chooses **per `(task, trial)`**, not per task: for each
cell, the profile among `eligible(p, t)` maximizing `Q` under
§quality_fn v1, ties by the declared tie-break order. Choosing per
trial is deliberate — it is the true hindsight upper bound; aggregating
trials first would understate it. The report labels `oracle` as a
per-trial hindsight bound and never as executable policy.

**`oracle_budget`** (optional, reported only when the preset declares a
ceiling). As `oracle`, but restricted to cells with
`cost.value <= ceiling`. **The ceiling is per-cell, and that is the
only semantics.** A per-cell filter does not bound a summed arm cost,
so no aggregate-cost invariant is asserted for this arm; the test
asserts the ceiling holds for every *selected cell*. A global-budget
allocation is explicitly out of scope for E1 — it is a knapsack
problem, not a filter, and nothing in #109 asks for one.

**Invariants** (asserted in tests): `oracle` `Q` `>=` every other arm's
`Q` on the same matrix; no cost inequality is asserted for `oracle`;
for `oracle_budget`, every selected cell's cost `<=` the declared
ceiling — and no assertion is made about its summed cost.

## Cost and reporting contract

Normative. Storage without a producer is not a contract, so this
section names where a cost value comes from, when two costs may be
compared, and what the report emits.

**Producers, without reversing the harness cost constraint.**
`specs/benchmark-harness/spec.md` § Constraints declares dollar-cost
reporting "permanently out of scope until billing-correlation is
solved across providers; no schema slot for cost estimation is added",
and `test_no_dollar_cost_in_backend_metadata`
(`scripts/benchmark_runner/tests/test_claude_code_backend.py`) enforces
it by asserting `total_cost_usd` never reaches `backend_metadata`.

E1 therefore does **not** add cost to `BackendResult`, to
`backend_metadata`, or to any shared harness schema. The
`routing_hybrid` scenario reads `total_cost_usd` from the backend's own
transcript into E1's routing-eval-owned `routing-run.schema.json`.
The harness constraint, its schema slot absence, and its guarding test
all stay intact and unmodified; cost exists only inside the routing
evaluation that declares a `cost_basis` for it.

| Provenance | Producer | Notes |
|---|---|---|
| `measured` | `total_cost_usd` read from the backend transcript by the routing-eval reader | The in-tree precedent is `rb_measured_cost` (`scripts/lib/routing-probe.sh`), which reads exactly this field and requires it to be a number `>= 0`. Claude Code headless (`--output-format json`) emits it. Read by E1's own reader, never surfaced through `backend_metadata`. |
| `estimated` | `tokens × price_table: v1` | A versioned price table checked into the repo. The version is recorded in every record and in the report. |
| `unavailable` | neither is obtainable | Propagates to `insufficient_evidence`; never defaulted. |

`stats.cost_reporting.enabled` stays `const: false` and is not relaxed.
E1 carries cost in its own record; the frozen schema is untouched.

**Provenance homogeneity.** A comparison declares exactly one
`cost_basis`, either `measured` or `estimated@<price_table_version>`,
and **every cell used for cost must satisfy it**. Mixed provenance is
refused everywhere cost is used — baseline selection, the cost axis,
the Pareto frontier, `oracle_budget`. If any eligible cell cannot meet
the declared basis, the cost axis is `insufficient_evidence` for the
whole comparison rather than partially drawn. This supersedes the
narrower "measured-only" rule: what matters is that costs being
compared were produced the same way.

**Reported outputs.** The report emits exactly three things on the
cost-quality view: `Q` per arm (§quality_fn v1), cost per arm under the
declared basis, and the Pareto frontier over arms. Quality metrics are
always reported as the full vector of §Metric contract beside `Q`.

**AIQ is not part of E1.** An AIQ-family scalar summarizes the area
under a router's cost-quality *curve*, which presupposes a tunable cost
knob tracing a family of operating points. The CCT router is a single
operating point under a given registry — there is no curve to
integrate, so an "AIQ" here would be an invented ratio rather than the
published metric. E1 therefore reports `Q`, cost, and the Pareto
frontier only. If a tunable knob is ever introduced, defining AIQ
becomes meaningful and is a later increment's work.

**One global component mask.** The `not_applicable` component mask and
its renormalized weights (§quality_fn v1) are computed **once** over
the complete report matrix — every arm, task, profile and trial in the
comparison — *before* any control selection runs, and that single mask
is then used identically for every cell and every arm, including the
oracle's per-cell choice. Per-cell mask derivation is forbidden: it
would let different cells score under different weightings, which
silently breaks comparability.

## Files

| Path | Change |
| --- | --- |
| `benchmarks/schema/routing-run.schema.json` | NEW — decisions 4, 7: telemetry with provenance + per-task routing decisions |
| `benchmarks/schema/outcome-matrix.schema.json` | NEW — decision 3: `task × profile × trial` cells + reuse fingerprint |
| `benchmarks/schema/compare-config.schema.json` | extend: `scenario`, `arms[]` (decision 1) |
| `benchmarks/presets/hybrid-routing.json` | NEW — the hybrid scenario preset + event stream |
| `benchmarks/adapters/routing_hybrid/` | NEW — scenario driver; drives the existing test seams (decision 2) |
| `benchmarks/scenarios/outcome_matrix.py` | NEW — matrix sweep, fingerprint gate, derived control arms (decision 3) |
| `benchmarks/report/quality_fn.py` | NEW — versioned `quality_fn: v1` + deterministic ties (decision 5) |
| `benchmarks/report/routing_quality.py` | NEW — #109 metrics, Pareto, control-set gate (decisions 4, 5, 6) |
| `benchmarks/report/price_table_v1.json` | NEW — versioned estimator table (§Cost and reporting contract) |
| `benchmarks/report/cost_reader.py` | NEW — routing-eval-owned `total_cost_usd` reader + estimator fallback |
| `benchmarks/report/redaction.py` | NEW or extend — decision 8 |
| `benchmarks/tests/` | regressions per task below |
| `README.md`, `CHANGELOG.md` | document the scenario and its artifacts |

**No production routing file appears in this table, and that is a
contract**: per decision 2, a diff touching `scripts/lib/routing-*.sh`,
`scripts/routing-cli.sh`, or `scripts/cooldown-supervisor.sh` is a
defect in this increment. Exact module placement is confirmed against
the runner's existing package layout in T1 before any code is written.

## Test Strategy

- **Schema**: every emitted artifact validates against its schema;
  a record missing `schema_version`, preset digest, or registry digest
  is rejected.
- **Determinism**: the same preset and pinned task set produce the
  same injected event stream and the same derived control arms across
  two runs.
- **Control-set gate**: a report built with a missing or
  `insufficient_evidence` control arm refuses to emit a `cct_router`
  figure (decision 6) — asserted as a failure, not a warning.
- **Oracle sanity**: oracle quality under the declared `quality_fn` is
  `>=` every other arm's on the same matrix. No cost inequality is
  asserted for `oracle` (decision 5); the cost ceiling is asserted only
  for an `oracle_budget` arm when one is reported.
- **Quality function**: `quality_fn: v1` is deterministic — the same
  metric vectors produce the same ordering across runs and across
  input permutation; declared tie-breaks resolve every tie; the report
  names the version it used and carries the full metric vector beside
  the scalar.
- **Telemetry provenance**: a cost tagged `estimated` carries its
  estimator and inputs; a cost tagged `unavailable` propagates to
  `insufficient_evidence` for `always_cheapest` and the cost axis,
  and is never rendered as zero. Verifier evidence
  references resolve to readable artifacts.
- **Matrix validity**: cells are keyed by `(task, profile, trial)` and
  trials are not collapsed; derived arms expose `not_applicable` for
  every sequence-dependent measure; a matrix whose fingerprint differs
  in ANY of the five components — `registry_digest`, `preset_digest`,
  `execution_identity`, `task_set_revision`, `toolchain_digest` — is
  refused for reuse, with one mismatch test per component.
- **Cost provenance**: a valid non-negative `total_cost_usd` yields
  `measured`; an invalid, negative, or non-numeric value does NOT
  become `measured`; a transcript without one falls through to the
  versioned estimator or to `unavailable`. `backend_metadata` still
  carries no cost, and `test_no_dollar_cost_in_backend_metadata`
  passes unmodified.
- **Injection seam**: the scenario drives only
  `CCT_SUPERVISOR_HARNESS_CMD` and `CCT_ROUTING_PROBE_CMD`; a guard
  test asserts the increment's diff touches no production routing
  file (decision 2).
- **Redaction**: a run seeded with a known credential value, an
  authorization header, and a sensitive absolute path emits artifacts
  containing none of them; a venv, a `__pycache__`, and a generated
  file do not appear in the changed-file measure.
- **Insufficiency**: an arm with no available backend reports
  `insufficient_evidence` with a reason and does not appear as a zero
  in the Pareto set.
- **Scenario legs**: the hybrid scenario visits every leg of the
  #109 §12 arc — failover, bounded Tier-2, recovery, reconciliation —
  and the artifact proves each leg was exercised.
- **No-runtime-change**: the existing routing suites (recovery,
  failover, delegation, config) pass unmodified *and* the diff-guard
  above holds. Passing suites alone does not prove runtime behaviour
  was untouched — the guard is what proves decision 10.
