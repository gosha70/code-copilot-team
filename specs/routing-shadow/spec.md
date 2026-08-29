# Spec: routing analysis + shadow-mode recommendations (E2 of #109)

Increment E2 (#261), the final increment of #109. E1 (#260, merged
97d372c) produces the evidence; E2 reads it. E2 surfaces routing
quality through the existing session-analytics pipeline and Studio,
and derives shadow-mode routing recommendations — claims about what
routing would have been better, presented beside what actually
happened, carrying no execution authority whatsoever.

Grounding (verified 2026-08-27): the session-analytics arc (#63)
ships `scripts/session_analytics/` (pipeline + FastAPI API on
127.0.0.1) and `studio/` (Next.js UI with typed fetchers in
`lib/api.ts`, a `TABS` nav, shared `Card`/`Stat`/`useApi`
components). The benchmark comparison tab
(specs/session-analytics-benchmark-ui) is the direct precedent for a
read-only artifact-consuming Studio surface. E1's artifacts are:
`routing-runs.jsonl` (published by `run_hybrid_scenario` through the
redacting writer), the outcome matrix (`matrix_dumps` canonical
JSON), and the comparison report computed by
`routing_eval.routing_quality.build_report` — which E1 computes but
does not yet persist.

## User Scenarios

- US1: As an operator, I open the Studio's Routing view and see, per
  E1 evidence set: the arms (cct_router + controls), each arm's `Q`,
  full metric vector, and cost, and the Pareto frontier or its
  withholding reason — E1's figures verbatim, never re-derived.
- US2: As an operator, I see actual routing beside suggested routing
  per task: which profile the router actually selected (with its
  recorded outcome) and which profile the evidence says would have
  been better, with the divergence explicit — quality and cost deltas
  from E1's own numbers.
- US3: As an operator, every recommendation I read carries the
  evidence it was derived from (addressable artifact references I can
  re-read), a confidence statement with its basis (never a bare
  number), and — when the evidence does not support a claim — an
  explicit insufficient-data state that is visibly distinct from "no
  change recommended".
- US4: As an operator with no E1 evidence ingested, the view says so
  plainly and points me at the E1 scenario, instead of an empty
  broken table.
- US5: As the router, nothing changed: no code path I execute reads a
  recommendation, and no registry or policy key exists that could
  make one effective.

## Requirements

- FR-E2-1: **Evidence discovery, validation, and BINDING.** The
  analytics layer discovers E1 evidence sets (routing-run artifact +
  outcome matrix + report) under configured evidence roots,
  read-only, identified by an opaque set id — never a filesystem
  path. Before anything renders or derives: every artifact validates
  against its schema (`routing_eval.record_check`, fail-closed —
  including the report, which gains its own schema); the report's
  source-artifact hashes verify against the actual artifact bytes
  (hash and parse the same bytes); and the fingerprints agree
  pairwise — report ↔ matrix on all five components, runs ↔
  report/matrix on the four components runs records carry. Any failure is a SET-level
  `invalid_evidence` state with the named reason — rendered, never
  partially rendered, never silently skipped, and never a source of
  recommendation records.
- FR-E2-2: **The evidence set is produced and persisted by E1's own
  orchestration.** A single E1 production entrypoint
  (`publish_evidence_set`) drives the hybrid scenario, the matrix
  sweep (via the new fixed-profile executor `run_profile_cell`), the
  control selections, and the report from ONE validated run context
  and publishes all three artifacts SET-atomically (staged, validated
  in staging, one atomic rename — no discoverable partial set) — the labeled E1
  contract addition in this increment per #261's rule ("If E2 needs
  a measure E1 does not emit, that is an E1 change, not an E2
  workaround"). The persisted report is versioned and schema'd, and
  carries the full fingerprint, source-artifact hashes, per-arm
  selection provenance, and per-task figures (the intermediate
  values of E1's own aggregation pipeline). E2 never invokes
  selectors, quality_fn, or build_report itself, and never recomputes
  any figure.
- FR-E2-3: **No metric re-derivation, enforced.** Every figure the
  API serves that is a copy of an E1 artifact field carries an exact
  source pointer into one E1 artifact, or is a declared delta naming
  its two source pointers; each descriptor is identity-bound (it must
  name exactly its record's task, arm, and field — a resolvable but
  wrong pointer refuses even when values collide). The
  figure-provenance gate parses each artifact once and requires
  semantic (canonically parsed float64) equality with the pointed-at
  value, and exact equality with the recomputed declared subtraction
  for deltas — no lexical byte comparison, which JSON round-trips
  cannot honor. Confidence statistics (`trials`, `agreement`,
  `unevaluated_trials`, the grade) are statistics OF the derivation,
  not copies of artifact figures, so they carry no source pointers;
  their gate is recomputation — the serving resolver re-derives them
  from the canonical report and records and refuses the payload on
  any disagreement.
- FR-E2-4: **Shadow recommendations: positive observed-evidence
  dominance, per (evidence set, task).** A recommendation record
  derived ONLY from E1 evidence, carrying:
  - *evidence*: addressable references — `{evidence_set_id, artifact,
    locator}` (record indices / cell coordinates / arm+task keys /
    relative ledger paths) — that resolve and re-read; absolute paths
    and `..` segments are rejected, resolution is
    containment-checked;
  - *actual*: the router's per-trial selected-profile chain with
    delegation/reconciliation markers — display and evidence, never
    the trigger;
  - *the rule*: `switch_profile` requires POSITIVE evidence — an
    executable candidate arm (`always_best` or `always_cheapest`;
    the oracle is a named ceiling, never suggested) whose per-task
    quality strictly beats the router's at no greater cost under the
    declared basis (or equal quality at strictly lower cost).
    Identity difference alone recommends nothing: a router that
    outperforms every control gets `no_change_recommended`;
  - *confidence*: a closed grade (`high`|`moderate`|`low`, by the
    declared deterministic rule) plus its stated basis, never a bare
    number;
  - *outcome*: the closed three-state vocabulary where
    `insufficient_data` is produced only from VALID sets with
    insufficient figures (carrying the specific insufficiency
    references) and can never collapse into `no_change_recommended`;
    invalid sets produce the set-level state instead.
- FR-E2-5: **No execution authority.** Recommendations exist only in
  the analytics store and API payloads. No file the router reads at
  execution time contains or references them; no new registry,
  policy, or route-class key is introduced; the E1 diff guard over
  the production routing files extends to this increment, plus an
  executable guard that no production routing script references the
  recommendation storage or schema.
- FR-E2-6: **Redaction preserved end to end.** The surface renders
  only E1's write-time-redacted artifacts and adds no derived prose
  from un-scrubbed sources. A regression chains E1's boring-credential
  fixture through the analytics API and asserts the credential
  appears in no payload.
- FR-E2-7: **Calibration gate stance.** Shadow-only, stated and
  enforced: no learned or similarity/kNN policy, no recommendation
  feedback into selection, and an acceptance test that no
  recommendation writer targets any router-read path. #109's
  calibration gate is documented as governing any future move beyond
  shadow mode; E2 does not attempt to satisfy it.
- FR-E2-8: **Studio Routing view.** A Routing tab following the
  benchmark-ui conventions: typed fetcher mirroring the payload, the
  standard loading/error states, an explanatory empty state (US4),
  the evidence view (US1), the actual-vs-suggested comparison with
  explicit divergence (US2), and distinct rendering for the three
  recommendation outcomes (US3). No new npm dependencies.
- FR-E2-9: **Versioned contracts.** `report.schema.json` (the E1
  report contract v1) and `recommendation.schema.json` (closing
  FR-E2-4's vocabulary), both schema_version from day one; every
  persisted report and every served recommendation validates against
  its schema.
- FR-E2-10: **Validation.** API endpoint tests (FastAPI test client),
  derivation unit tests with counterexamples (fabricated evidence
  refused via schema validation; insufficiency distinctness;
  divergence arithmetic from E1 figures only), the verbatim gate,
  the authority guard, the redaction chain, and `cd studio && npm
  run build` green.

## Constraints

- Zero change to `scripts/lib/routing-*`, `scripts/routing-cli.sh`,
  `scripts/cooldown-supervisor.sh` (the executable diff guard holds).
- `scripts/benchmark_runner/` changes are limited to the labeled E1
  work of FR-E2-2: the `publish_evidence_set` orchestration, the
  additive report-v1 fields, `write_report`, and ONE explicitly
  labeled correction — the router lifecycle reduction (multiple
  records of one `(task, trial)` lifecycle fold to one metric cell
  per plan decision 3). E1 metric definitions, weights, selectors,
  and control semantics remain unchanged; existing E1 behavior
  remains green, with targeted E1 regressions extended for the
  corrected lifecycle reduction.
- The analytics dependency direction is one-way:
  `session_analytics` imports `benchmark_runner.routing_eval`
  read-only; nothing in `benchmark_runner` or the routing scripts
  imports from `session_analytics`.
- One issue per PR: this bundle covers exactly #261, and #261's merge
  closes it (close keyword only in the final PR body).

## Non-Goals

- Automatic policy changes, or any runtime routing behaviour change.
- Similarity/kNN or learned routing as execution authority (gated by
  #109's calibration gate, which E2 does not attempt).
- Re-deriving, reweighting, or extending the metrics E1 owns.
- Analytics for non-routing benchmark data (the existing benchmark
  tab already owns that).
- Live/streaming evaluation — E2 reads completed E1 evidence sets.
