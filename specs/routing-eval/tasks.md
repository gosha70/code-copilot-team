# Tasks: Hybrid routing evaluation — measurement substrate (E1 of #109)

Increment D merged as `ed8873b` (PR #259), so the scenario's recovery
and failback legs now have a runtime to exercise. Build entry is
unblocked.

Each task is independently verifiable and leaves the suite green.

## T1 — Contracts: preset kind, telemetry record, matrix record

- Confirm module placement against the runner's real package layout
  before writing code (plan.md §Files).
- Extend `compare-config.schema.json` with `scenario` and `arms[]`;
  a preset mixing `arms[]` and `candidates[]` is rejected.
- Add `routing-run.schema.json` carrying **every raw-evidence field
  named in plan.md §Metric contract** — the table is the checklist, and
  a metric whose source field is absent from the schema is a T1 defect:
  - identity: schema version, registry digest, preset digest, pinned
    task-set revision, injected event stream, per-task routing
    decisions in `explain`'s vocabulary;
  - telemetry: `tokens`; `cost.{value, provenance, estimator, inputs}`
    over the closed set `measured | estimated | unavailable`;
    `verifiers[]` with command, exit status and evidence reference;
    `repair_cycles[]` with `signature`; `interventions[]` as records;
  - **baselines** for rows 2–3: `baseline.{lint_passed,
    typecheck_passed}` captured before the attempt;
  - **new gate evidence** for rows 4–6:
    `quality_gates.coverage.{before, after}`,
    `quality_gates.security.findings_by_severity.{before, after}`,
    `scope_violations[]` (files changed outside the packet's declared
    file scope, reusing increment C's file-scope enforcement);
  - **sequence-dependent evidence** for rows 9–11:
    `tier2.{delegated, delegated_lines, reconciliation_diff_lines}`
    and `rollbacks[]`.
- Add the routing-eval-owned cost reader plus the versioned
  `price_table_v1.json` estimator, per plan.md §Cost and reporting
  contract. `measured` is `total_cost_usd` read from the backend
  transcript by E1's own reader (in-tree precedent: `rb_measured_cost`
  in `scripts/lib/routing-probe.sh`); `estimated` is tokens × price
  table; neither obtainable is `unavailable`.
- **The harness cost constraint is preserved, not reversed.** Cost is
  not added to `BackendResult`, `backend_metadata`, or any shared
  harness schema, so `specs/benchmark-harness/spec.md` § Constraints
  ("no schema slot for cost estimation is added") still holds and
  `test_no_dollar_cost_in_backend_metadata` passes unmodified.
- Cost-reader regressions: a valid non-negative `total_cost_usd`
  becomes `measured`; an invalid, negative, or non-numeric value does
  NOT become `measured`; a transcript with no usable value falls
  through to the versioned estimator, or to `unavailable` when tokens
  are also absent; `backend_metadata` still contains no cost.
- Add `outcome-matrix.schema.json`: cells keyed `(task, profile,
  trial)` plus the five-component reuse fingerprint — `registry_digest`,
  `preset_digest`, `execution_identity`, `task_set_revision`,
  `toolchain_digest` — all required.
- Regressions: every existing preset still validates unchanged; a
  record missing any digest or the schema version is rejected; a cost
  tagged `estimated` without an estimator is rejected; **a per-metric
  test asserts every row of §Metric contract has its source field
  present in the schema**; `stats`, `score`, and `run-record` schemas
  are unmodified.

## T2 — Deterministic injection through the existing test seams

- Drive `CCT_SUPERVISOR_HARNESS_CMD` and `CCT_ROUTING_PROBE_CMD` only.
  The benchmark supplies the child's output; the real, unmodified
  classifier does its real work on it.
- The event stream is preset-owned, recorded in the artifact, and part
  of the preset digest.
- Regressions: two runs of one preset see the same events in the same
  order; no leg depends on wall-clock timing; the router's
  classification of an injected transcript matches its classification
  of the equivalent real provider response; **a diff guard asserts no
  production routing file is modified by this increment.**

## T3 — Outcome matrix: trials, fingerprint gate, derived arms

- Sweep every eligible profile across every task and every trial in
  the pinned set; emit the `task × profile × trial` matrix as a
  versioned artifact with its reuse fingerprint.
- Implement the three control selectors exactly as plan.md §Control
  selectors defines them — including per-task eligibility, the
  declared-`cost_basis` rule for `always_cheapest`, and `oracle`
  choosing per `(task, trial)` rather than after trial aggregation.
- Mark rows 9–11 of §Metric contract `not_applicable` on derived arms;
  those are measured only for `cct_router`.
- Regressions: trials are not collapsed; **a mismatch test per
  fingerprint component** (registry, preset/seeds, execution identity,
  task-set revision, toolchain) refuses reuse; a task whose eligible
  profiles have no cell meeting the declared `cost_basis` makes
  `always_cheapest` `insufficient_evidence` rather than selecting on
  mixed provenance; oracle quality `>=` every other arm under the
  declared `quality_fn`; **no cost inequality is asserted for
  `oracle`**; for `oracle_budget`, every *selected cell* is `<=` the
  ceiling and **no assertion is made about its summed cost**.

## T4 — The hybrid scenario

- Drive the #109 §12 arc: preferred Tier-1 build → injected
  usage-limit → next Tier-1 profile → bounded Tier-2 task →
  preferred-profile recovery → Tier-1 reconciliation.
- Add `benchmarks/presets/hybrid-routing.json` covering the six task
  shapes #109 names, including the Tier-1-only negative controls.
- **Leg completeness is proven from durable evidence, never from a
  driver-maintained visited-legs list** (owner design rule, pinned
  pre-T4): the proof reads routing-run records and state transitions,
  so the scenario cannot claim it exercised failover/recovery/
  reconciliation merely because orchestration code attempted them.
  Specifically: the Tier-2 task became provisional AND that same
  provisional work was later reconciled by Tier-1; recovery SELECTED
  the preferred profile at a task boundary (not merely observed a
  passing probe); and the Tier-1-only negative controls demonstrably
  REFUSED Tier-2 rather than merely ending up on Tier-1.
- Regressions: the artifact proves every leg was exercised; a run
  missing a leg fails rather than reporting a partial arc.

## T5 — Quality function, metrics, and the control-set gate

- Implement `quality_fn: v1` exactly as plan.md §quality_fn v1 defines
  it: components rows 1–8 only, the stated normalization, the fixed
  weight table, weight renormalization when a component is dropped as
  `not_applicable` for any arm, `Q` withheld entirely when any
  component is `insufficient_evidence`, and the declared tie-break
  sequence (which does **not** include reconciliation rework).
- Implement every row of §Metric contract with its stated formula,
  aggregation, applicability, and missing-value behaviour. Ratio
  metrics aggregate as sum-of-numerators over sum-of-denominators,
  never as a mean of per-cell ratios; a zero denominator is
  `not_applicable`, not zero. Cost and elapsed stay secondary.
- Emit `Q` per arm, cost per arm under the declared `cost_basis`, and
  the Pareto frontier — always beside the full metric vector. No AIQ
  scalar is emitted (plan.md §Cost and reporting contract).
- Compute the `not_applicable` component mask and its renormalized
  weights ONCE over the complete report matrix, before any control
  selection, and use that single mask everywhere including the
  oracle's per-cell choice.
- Enforce the control-set gate: refuse to emit a `cct_router` figure
  unless all three controls are present for the same task set, trial
  seeds, and event stream.
- Regressions: the gate fails the report (not warns); ordering is
  deterministic under input permutation; every declared tie-break
  resolves its tie; dropping a `not_applicable` component renormalizes
  the weights to `1.0`; one `insufficient_evidence` component withholds
  `Q` for the whole comparison; the report names its `quality_fn`
  version and carries the full metric vector beside the scalar; a
  metric absent from §Metric contract is not emitted.

## T6 — Provenance, redaction, insufficiency, reproducibility

- Propagate `unavailable` cost provenance to `insufficient_evidence`
  for `always_cheapest`, the cost axis, and the Pareto frontier —
  never a zero, never a default. A comparison whose cells cannot all
  meet the declared `cost_basis` withholds the cost axis entirely
  rather than mixing provenance.
- Scrub secrets, authorization headers, API keys, connector
  inventories, and sensitive absolute paths at write time; exclude
  venvs, caches, bytecode, and generated runtime noise from the
  changed-file measure.
- Record `insufficient_evidence` with a reason for any arm that cannot
  run; never render it as zero, drop it from the Pareto set, or let it
  satisfy the T5 control-set gate.
- Regressions: a run seeded with a known credential, header, and
  sensitive path emits none of them; verifier evidence references
  resolve to readable artifacts; two runs of the same versioned inputs
  are comparable.

## T7 — Docs, gates, sweep

- Document the scenario, its arms, its artifacts, the `quality_fn`
  contract, and how to read the report in `README.md`; record the
  increment in `CHANGELOG.md`.
- Prove plan.md decision 10: the routing suites pass unmodified **and**
  the T2 diff guard holds.
- Full sweep, origin-alignment record refresh, and test-count updates.
