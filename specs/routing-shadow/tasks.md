# Tasks: routing analysis + shadow-mode recommendations (E2 of #109)

Sequential; each task lands only after its regressions pass and the
running verification gates stay green. The E1 diff guard over the
production routing files holds for every task.

## T1 — The E1 evidence-set orchestration (the labeled E1 change)

- `run_profile_cell` (decision 2): the NEW fixed-profile matrix
  executor — per-cell clean adapter-lifecycle worktree, injected-event
  parity with the router arm, pinned-profile launch environment with
  exact executed identity recorded, driver-owned adapter
  verification, harvest to a `mode: "profile_sweep"` record and
  matrix `Cell`.
- `publish_evidence_set` (decision 2): hybrid scenario + matrix sweep
  via `build_matrix` with `run_profile_cell` (eligible tuples
  executed; ineligible tuples materialized unexecuted per the
  existing contract) + selections under the derived authority
  context + `build_report` — then SET-ATOMIC publication per the
  closed semantics: hidden same-filesystem staging excluded from
  discovery, in-staging validation with the manifest written last,
  one atomic rename to the set-id target, idempotent no-op on
  byte-identical duplicate, refusal on differing content,
  owner-checked stale-staging cleanup. Fault-injection regressions
  after each step: no discoverable partial set remains and the rerun
  succeeds.
- The launch-bridge parity pins (decision 2): derived single-profile
  registry through the UNMODIFIED supervisor; launch-env wiring
  parity vs production for the same profile; build vs bounded-build
  role split for ordinary vs delegate cells; all seven executed
  identity fields verified against the matrix fingerprint entry.
- The router LIFECYCLE FOLD (decision 3, the labeled E1 correction):
  one folded figure per (task, trial) — reconciled outcome scores,
  provisional never separately; cost summed across legs under
  provenance homogeneity; duplicate/missing folded entries refuse.
  Pinned regression: a delegated task folds to ONE cell, not two.
- `manifest.json` + evidence-manifest.schema.json (decision 4): three
  artifact hashes + evidence_files map; the set id is the manifest's
  canonical-bytes sha256; a schema-valid edit to ANY artifact
  (report included) changes the identity — pinned regression.
- Report contract v1 (decision 3): NEW `report.schema.json`;
  additive report fields — schema_version, full fingerprint,
  `source_artifacts` sha256 bindings (hashed from the same bytes
  written), per-arm selection provenance, the per-task figure table
  (E1's own intermediate aggregation values, emitted not
  re-derived) — plus `write_report`.
- Regressions: the persisted report validates against its schema;
  source-artifact hashes verify against the published bytes;
  byte-reproducibility on identical input; freshness refusal; a
  live end-to-end publication through the T4-era fixture machinery
  producing a complete, binding-consistent evidence set.
- Explicitly labeled an E1 contract addition (#261's rule); ADDITIVE
  only — no metric, selector, or gate semantics change; the E1
  suites pass unmodified.

## T2 — recommendation.schema.json + the derivation module

- `benchmarks/schema/recommendation.schema.json` (decision 5): closed
  outcome vocabulary, evidence-reference shapes, confidence-basis
  fields, additionalProperties false.
- `session_analytics/routing_evidence.py` (decisions 4–5): evidence
  set discovery under configured roots with opaque set ids; the full
  binding validation (schemas, source-artifact hashes over the same
  bytes parsed, fingerprint agreement) with `invalid_evidence` as a
  SET-level state; deterministic derivation per the normative
  contract table — the dominance rule, the confidence grade rule,
  the per-trial actual structure.
- Regressions: fabricated/mixed evidence refused (a valid matrix from
  another run fails the hash binding); unresolvable, absolute, or
  `..`-bearing evidence reference invalidates the recommendation;
  the owner's dominance counterexample (router outperforms
  always_best ⇒ NO switch); equal-quality-cheaper ⇒ switch to
  always_cheapest; agreement computed by the full two-axis per-trial
  dominance predicate (a quality-only agreement mutation
  discriminates); unpriced per-trial cost caps the grade at low with
  the trial named; `insufficient_data` for every insufficiency
  source in a VALID set and never collapsed into
  `no_change_recommended`; invalid sets produce no records;
  divergence is the declared float64 subtraction of served figures
  only; byte-identical derivation on identical inputs; every derived
  record validates against recommendation.schema.json.

## T3 — API endpoints + the three enforcement gates

- Routing evidence + recommendation endpoints on the existing FastAPI
  app; evidence roots wired end to end — `AnalyticsConfig` field,
  defaults, env/file layering tests, `/api/settings` exposure — like
  the existing source roots.
- The figure-provenance gate (decision 9 — source pointers, semantic
  equality, recomputed declared deltas), the authority guard
  (decision 7 — diff guard extension + no-production-reference +
  writes only under the analytics store), and the redaction chain
  (decision 8 — E1's boring-credential fixture through evidence-set
  publication into API payloads; no absolute path in any payload).
- FastAPI endpoint tests for the evidence, recommendation, empty, and
  invalid states.

## T4 — Studio Routing view

- Typed fetchers mirroring the payloads; Routing tab; evidence view
  (arms, Q, vector, cost, frontier/withholding), actual-vs-suggested
  comparison with explicit divergence, three visually distinct
  recommendation outcomes, explanatory empty state, and the
  set-level `invalid_evidence` state with its sanitized code.
- No new npm dependencies; `cd studio && npm run build` green.
- Browser verification, not compiler-only: rendered assertions and
  screenshots against a live API fixture for the valid, invalid,
  empty, and all three recommendation-outcome states, at desktop and
  mobile widths, through the repo's UI-harness/visual-review loop.

## T5 — Docs, gates, closure

- README + CHANGELOG + studio/README: the surface, the shadow-mode
  contract (evidence/confidence/insufficiency), and the calibration
  gate stance.
- Decision-10 proof re-run: routing shell suites unmodified at their
  pins; diff guard; E1 suites green (the T1 addition included).
- Full CI-exact sweeps (benchmark_runner + session-analytics test
  suites), origin-alignment refresh, test-count updates if any shell
  suite changed (none expected).
- #261 closes with the PR's merge; close keyword only in the PR body.
