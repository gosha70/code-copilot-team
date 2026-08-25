# Spec: Hybrid routing evaluation — measurement substrate (E1 of #109)

A–D built a router that chooses, fails over, delegates, reconciles,
and recovers. Nothing yet says whether those choices were *good*.
Increment E1 supplies the evidence: a hybrid benchmark scenario that
exercises the whole failover→Tier-2→recovery→reconciliation arc, the
routing-quality metrics #109 already prescribes, and — the part #109
leaves open — the comparison frame that makes those numbers
interpretable.

The governing rule: **a routing result is meaningless without its
controls.** A pass rate of 0.82 says nothing until you know what
always-best, always-cheapest, and a perfect-hindsight oracle scored on
the same tasks. E1 refuses to publish a router score that is not
accompanied by its control set.

E1 is measurement only. It produces artifacts. It does not display
them, does not recommend anything, and does not change routing
behaviour at runtime — those are E2.

## User Scenarios

- A maintainer wants to know whether Tier-2 delegation is costing
  quality. They run the hybrid preset; the report places the CCT
  router, always-best, always-cheapest, and the oracle on one
  cost-quality plane and reports how much of the oracle's achievable
  quality the router captured, at what fraction of always-best's cost.
- A maintainer changes `minimum_profile_dwell_sec` and wants evidence
  the change helped. They re-run the same versioned preset against the
  same pinned task set; because run artifacts are versioned and
  reproducible, the two reports are directly comparable.
- A reviewer distrusts a headline number. Every routing decision in
  the run — candidates considered, profile selected, why, what failed,
  what was delegated, what was reconciled — is reconstructable from the
  durable artifacts, without re-running anything.
- A contributor runs the suite on a machine with no local Tier-2
  backend. The scenario reports `insufficient_evidence` for the
  Tier-2 arms rather than silently scoring a degenerate run.

## Requirements

- **FR-E1-1 (hybrid routing scenario).** A benchmark scenario drives
  the arc named in #109 §12: preferred Tier-1 build → injected
  usage-limit event → next Tier-1 profile → optional bounded Tier-2
  task → preferred-profile recovery → Tier-1 reconciliation. Provider
  events are *injected deterministically*; the scenario never waits on
  real quota exhaustion, and never depends on wall-clock timing for
  correctness.

- **FR-E1-2 (telemetry record with explicit provenance).** E1 owns its
  own telemetry record, because the evidence it needs does not exist
  today: `stats.schema.json` fixes `cost_reporting.enabled` to `false`
  and carries no cost amount, and `score.schema.json` records only a
  `failed_commands` count and a `human_interventions` count — not the
  commands, the evidence, or the interventions. The record carries,
  per attempt: input/output/cache tokens; a cost value tagged
  `measured | estimated | unavailable`, naming the estimator and its
  inputs whenever it is `estimated`; each verifier execution with its
  command, exit status, and an addressable evidence reference; repair
  cycles with repeated-failure signatures; and human-intervention
  records. `measured` comes from the backend's own reported spend
  (`total_cost_usd`), `estimated` from tokens × a versioned price
  table; a measure whose provenance is `unavailable` propagates as
  `insufficient_evidence` (FR-E1-8) and is never silently defaulted.

- **FR-E1-3 (the comparison unit is a routing policy).** The existing
  harness compares candidates that fix a backend and model. E1 adds a
  comparison axis whose unit is a *routing policy* evaluated over the
  same task set, trial seeds, and event stream. Four arms are
  mandatory:
  - `always_best` — the highest capability tier for every task, ties
    broken by the selector's existing total order (priority ascending,
    then profile id lexical ascending), so the baseline is
    reproducible and not an artifact of registry order.
  - `always_cheapest` — per task, the eligible profile with the lowest
    mean cost across that task's trials, computed only from cells
    satisfying the comparison's declared `cost_basis`. A task whose
    eligible profiles have no cell meeting that basis is
    `insufficient_evidence`; mixed provenance is never used.
  - `oracle` — best per `(task, trial)` under the versioned quality
    function of FR-E1-5; a per-trial hindsight upper bound, never
    executable policy.
  - `cct_router` — the real router under a named registry.

- **FR-E1-4 (authoritative metrics).** The primary measures are
  #109's, unchanged and not substituted: final verifier pass rate;
  lint, type, coverage, and security regressions; Tier-2 tasks
  accepted unchanged; Tier-1 reconciliation rework ratio; rollbacks;
  architecture or scope violations; repeated repair cycles; human
  intervention. Cost and elapsed time are secondary measures and are
  never traded against a primary measure implicitly. Every report
  carries the full metric vector; no scalar replaces it.

- **FR-E1-5 (versioned quality function, for ordering only).**
  Ordering arms requires a total order over a metric *vector*, so E1
  defines an explicit, versioned quality function `quality_fn: v1`
  with deterministic tie-breaking. It is a **reporting projection used
  only for ranking and for the oracle's per-cell choice** — it does
  not reweight, combine, or replace the metrics of FR-E1-4, which are
  always reported alongside it. A report states which `quality_fn`
  version produced its ordering, and two arms that tie under it are
  ordered deterministically rather than arbitrarily.

- **FR-E1-6 (trial matrix with a trial dimension).** The outcome
  matrix is `task × profile × trial`; trials are not collapsed. Trial
  seeds and injected-event identity are *paired* across arms, so every
  arm sees the same trial under the same conditions. Coverage spans
  the task shapes #109 names: isolated one-file implementations,
  three-to-five file features, refactors, reproduced bugs, integration
  tasks, and explicit Tier-1-only negative controls. Trial count is
  preset-owned and recorded; a single-trial run is labelled as such
  and never reported as a rate.

- **FR-E1-7 (what controls may and may not derive).** Control arms are
  derived from independent per-task cells, so they may only carry
  measures that are independent per task — verifier outcome,
  regressions, cost, elapsed time. Sequence-dependent measures that
  only exist along a stateful run — Tier-1 reconciliation rework
  ratio, Tier-2 accepted unchanged, failback behaviour, rollbacks
  arising from a switch — are reported as `not_applicable` for
  derived arms and are measured only for `cct_router`. A report never
  presents a derived arm as though it had a sequence-dependent
  measure.

- **FR-E1-8 (comparison frame).** Results are reported as `Q` per arm
  (the declared `quality_fn`), cost per arm under the declared
  `cost_basis`, and the Pareto frontier over the arms. The oracle
  bounds the quality axis; the two fixed policies anchor it.
  Publishing a `cct_router` figure without a complete control set is a
  hard error, not a warning. Every cell used for cost must satisfy one
  declared `cost_basis`; where it cannot, the cost axis and the
  frontier are withheld as `insufficient_evidence` rather than drawn
  from defaults or mixed provenance. No AIQ-family scalar is emitted —
  it presupposes a cost-quality curve E1's single-operating-point
  router does not trace.

- **FR-E1-9 (versioned, reproducible artifacts).** Every run emits a
  schema-validated routing-run record carrying its schema version, the
  preset digest, the registry digest, the pinned task-set revision,
  the injected event stream, and per-task routing decisions. Two runs
  of the same versioned inputs produce comparable records. Artifacts
  exclude virtual environments, caches, bytecode, and generated
  runtime noise, and carry no credential values, authorization
  headers, connector inventories, or sensitive absolute paths.

- **FR-E1-10 (explainability from artifacts alone).** Every routing
  decision recorded during the run is reconstructable from the durable
  artifacts without re-execution: candidates considered, verdict per
  candidate, selected profile and reason, requested and effective
  model, sanitized upstream endpoint, failure classification, and
  provisional/reconciliation outcome.

- **FR-E1-11 (honest insufficiency).** When an arm or a measure cannot
  be obtained — no local Tier-2 backend, an unavailable provider, too
  few trials, cost provenance `unavailable` — the report states
  `insufficient_evidence` with the reason. It is never rendered as a
  zero, never silently dropped from the Pareto set, and never allowed
  to satisfy the control-set requirement of FR-E1-8.

## Constraints

- **No runtime routing change.** E1 adds no key the router reads at
  execution time, no new policy surface, and no code path that can
  alter a routing decision. This is what makes E1 independently
  verifiable and lets E2 depend on it as a stable evidence contract.

- **Injection uses existing test-only seams; production routing code
  is not modified.** Provider outcomes are supplied by driving the
  documented mock-harness seams — `CCT_SUPERVISOR_HARNESS_CMD`
  (cooldown-supervisor.sh) and `CCT_ROUTING_PROBE_CMD`
  (routing-probe.sh) — so the benchmark produces the *child output*
  and the real, unmodified classifier does its real work on it.
  E1 never injects at, patches, or bypasses the classification
  boundary itself.

- **Frozen upstream contracts.** `run-record`, `score`, and `stats`
  schemas are consumed as-is and extended by reference. In
  particular `stats.cost_reporting.enabled` is `const: false` and is
  not relaxed by this increment; E1 carries cost in its own record
  with explicit provenance instead.

- **Matrix reuse is fingerprint-gated.** A stored outcome matrix may
  be reused only when all five components match: `registry_digest`,
  `preset_digest` (trial count, trial seeds, injected event stream,
  arm set), `execution_identity` (profile id, backend, provider,
  requested and effective model, tool profile, sanitized endpoint),
  `task_set_revision`, and `toolchain_digest`. Any mismatch
  invalidates reuse; a registry edit or a seed change never silently
  reuses stale cells.

- **Bounded cost.** The matrix sweep is the expensive step and is
  executed once per fingerprint, with its trial count preset-owned
  and recorded. Re-evaluating a router change costs one router run,
  not a full re-sweep.

- **Redaction at write time.** Secret values, authorization headers,
  API keys, connector inventories, and sensitive absolute paths are
  scrubbed where the record is written, not where it is read.

## Non-Goals

- Any analytics UI, studio surface, or session-analytics presentation
  (E2).
- Shadow-mode routing recommendations or actual-vs-suggested
  comparison (E2).
- Similarity/kNN or any learned routing policy — #109 gates these
  behind calibration that E1 exists to make possible.
- Changing runtime routing behaviour in any way. E1 adds no execution
  authority and no new policy key the router reads.
- Replacing or reweighting #109's metric set.

## Dependencies

- **Increment D — satisfied.** PR #259 merged as `ed8873b`
  (2026-08-25). E1 measures the recovery and failback behaviour D
  introduces; that runtime now exists.
- Increment C's `verified_provisional` and reconciliation flow, for
  the Tier-2 and reconciliation legs.
- The existing benchmark harness: `benchmarks/adapters/`,
  `benchmarks/presets/`, `benchmarks/schema/`, and the run-record,
  score, and stats schemas E1 extends rather than replaces.
