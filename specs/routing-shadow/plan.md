---
spec_mode: full
feature_id: routing-shadow
status: draft
date: 2026-08-27
risk_category: integration
justification: >
  Adds a read-only consumption surface over E1's evidence contract:
  session-analytics evidence discovery/validation, shadow-mode
  recommendation derivation with a new versioned record schema, API
  endpoints, and a Studio view — plus one labeled E1 contract
  addition (persisting the comparison report). Integration risk
  across the analytics pipeline, the Studio, and the frozen E1
  artifact contracts — but it adds no runtime execution authority,
  changes no routing behaviour, and the router can read none of it.
origin:
  type: issue
  issue: 261
  parent: 109
  references:
    - "#261 issue body — the E2 scope, shadow-mode contract (evidence/confidence/insufficient-data), acceptance list, dependency rule ('an E1 change, not an E2 workaround'), and non-goals"
    - "#109 §Delivery Plan Increment E — 'Studio/session-analytics surface' and 'Shadow-mode routing recommendations' (the two E deliverables E1 left; kNN stays gated)"
    - "#109 §11 Telemetry and explainability — secrets, auth headers, API keys, connector inventories, and sensitive absolute paths never enter analytics or public artifacts"
    - "#109 Acceptance §Evaluation and observability — 'Learned routing remains shadow-only until explicit calibration gates are met' (the one remaining unchecked box)"
    - "The owner's E1/E2 split directive (2026-08-25): E2 depends on a stable evidence contract"
    - "specs/routing-eval/ — E1's frozen evidence contract: routing-run.schema.json, outcome-matrix.schema.json, build_report's output shape, the write-time redaction gate"
    - "specs/session-analytics-benchmark-ui/ — the precedent for a read-only artifact-consuming Studio surface"
---

# Plan: routing analysis + shadow-mode recommendations (E2 of #109)

## Decisions

1. **Placement: consumption and derivation live in session
   analytics.** New module
   `scripts/session_analytics/routing_evidence.py` owns evidence-set
   discovery, validation, and shadow-recommendation derivation; API
   routes join the existing FastAPI app; the Studio gains a Routing
   view. The dependency direction is one-way — `session_analytics`
   imports `benchmark_runner.routing_eval` READ-ONLY (record_check
   validation, matrix/record parsing) — mirroring #261: "Consume E1
   artifacts through session analytics / studio". Nothing under
   `scripts/lib/`, `benchmark_runner`, or the supervisor imports
   analytics.

2. **E1 gains ONE production orchestration entrypoint that publishes
   the complete evidence set — the labeled E1 change.** Today
   `run_hybrid_scenario` publishes only `routing-runs.jsonl`;
   `build_matrix` and `build_report` have no production callers, and
   NO fixed-profile executor exists (`SupervisorRunner.run_task`
   invokes the router and harvests `mode: "cct_router"` only). T1
   adds, in `routing_eval`:
   - **`run_profile_cell(task, profile_id, trial, seed, events)`** —
     the fixed-profile matrix executor. The launch BRIDGE is the
     production supervisor itself under STAGE-SPECIFIC derived
     registries — one profile per invocation, so "pinned" is
     mechanically true rather than hoped: roles are not mutually
     exclusive in the registry grammar, and a two-profile registry
     can legally let the production selector pick the reconciler as
     builder (both holding bounded-build), mis-attributing or
     un-executing the cell. Instead: the BUILDER invocation runs
     under a derived registry containing ONLY the pinned profile's
     table entry (copied byte-for-byte from the declared full
     registry) with route classes admitting exactly it; for
     delegate-class cells the RECONCILIATION invocation runs
     under a second derived registry containing ONLY the declared
     Tier-1 reconciler's entry. Profile-to-environment translation
     (provider endpoints, credential references, tool profiles) and
     T2's event seam run through the same `cooldown-supervisor.sh`
     code path production uses, never a reimplemented launcher.
     Ordinary tasks execute as `build`; delegate-class tasks execute
     the delegation lifecycle as `bounded-build` — matching the
     eligibility authority's role split exactly — and the SEVEN-field
     executed-identity parity assertion runs INDEPENDENTLY on each
     lifecycle leg (builder leg against the pinned profile's
     fingerprint entry; reconciliation leg against the reconciler's
     declaration). Each cell gets a CLEAN context (fresh
     worktree through the same adapter lifecycle — provision →
     prepare_task → install_dependencies — and the same freshness
     refusals the router arm gets) and the task's declared injected
     events with full parity to the router arm's stream. PARITY IS
     PINNED BY TEST: the launch-environment wiring journaled for the
     pinned profile equals production's for the same profile, and
     ALL SEVEN executed identity fields (profile id, backend,
     provider, requested model, effective model, tool profile,
     sanitized endpoint) are verified against the matrix
     fingerprint's execution_identity entry. The matrix fingerprint
     continues to carry the DECLARED full registry's digest — the
     derived registry is an execution mechanism whose profile entry
     must match the full registry's declaration, verified. Harvest
     is a `mode: "profile_sweep"` routing-run-shaped record converted
     to the matrix `Cell` (verifier outcome, regressions, scope,
     repair, intervention, cost with provenance).
   - **`publish_evidence_set(config, registry_path, runner, …)`** —
     from ONE validated run context: (a) the hybrid scenario (the
     router arm); (b) the matrix sweep via `build_matrix` with
     `run_profile_cell` as executor — every ELIGIBLE
     `(task, profile, trial)` executed, ineligible tuples
     materialized as unexecuted cells exactly per `build_matrix`'s
     existing contract (eligibility from the derived authority
     context, the registry's role + tier_order predicate); (c) the
     control selections with the declared selectors under that same
     context; (d) `build_report`; then (e) SET-ATOMIC publication
     with CLOSED crash and duplicate semantics: artifacts are written
     into a HIDDEN sibling staging directory on the same filesystem
     (a dot-prefixed name discovery structurally excludes), validated
     there (schemas + manifest bindings + fingerprint agreement — the
     same checks the E2 loader runs, manifest written last), then
     published by ONE atomic rename to the set-id-named target. If
     the target exists: byte-identical content verifies and returns
     the existing set as an idempotent no-op; differing content at
     the same id REFUSES — never an overwrite. Stale staging
     directories are cleaned only after an owner check (age + no
     live publisher). A failure at any step leaves no DISCOVERABLE
     partial set and a rerun succeeds; fault-injection regressions
     prove it after each publication step.
   Per #261's own rule this is an E1 change, made here, explicitly
   labeled, with its own tests. E2 reads persisted artifacts only and
   NEVER calls selectors, quality_fn, or build_report.

3. **Report contract v1: versioned, schema'd, task-resolved,
   source-bound (the second half of the labeled E1 change).** The
   current report emits aggregate arm figures with no schema version,
   no registry digest, no source identity, and no per-task
   provenance — insufficient for E2 and unvalidatable under FR-E2-1.
   The persisted report v1 ADDS (additively — no metric or gate
   semantics change):
   - `schema_version: 1` and a NEW closed
     `benchmarks/schema/report.schema.json` it validates against;
   - the FULL five-component fingerprint (registry digest, preset
     digest, execution identity, task-set revision, toolchain
     digest);
   - `source_artifacts`: sha256 of the canonical bytes of
     `routing-runs.jsonl` and `outcome-matrix.json`, computed at
     publication from the same bytes that were written — the binding
     that makes an evidence set a SET (finding: co-location binds
     nothing);
   - per-arm SELECTION provenance: the profile each control arm chose
     per task (per `(task, trial)` for the oracle) — the selector
     outputs build_report already verified, now emitted;
   - a per-task figure table: for every arm and task, the per-task
     quality projection and per-task cost — AND the per-trial values
     beneath them (each selected cell's quality projection and cost
     per `(task, trial)`, and the router's per-trial equivalents) —
     the intermediate values of E1's own declared aggregation
     pipeline (per-cell → per-task → arm), emitted, not re-derived.
     The per-trial values are what makes a non-hollow confidence
     grade derivable (decision 5) without E2 computing anything;
   - the router per-trial values come from a NORMATIVE LIFECYCLE
     FOLD (a labeled E1 correction — today router_cells_from_records
     converts every record to a cell, so a delegated task's
     provisional and reconciliation records double-weight that
     task): each `(task, trial)` folds to EXACTLY ONE metric cell,
     with a PER-COMPONENT contract — final-state evidence reduces
     from the final leg, but process evidence unions across the
     lifecycle (a clean reconciliation must never launder the
     provisional leg's process signals out of Q):
     | Component | Fold rule |
     |---|---|
     | verifier outcome (row 1) | the FINAL lifecycle outcome — the reconciled record's evidence for delegated tasks; the provisional leg never scores separately |
     | lint/type/coverage/security regressions (rows 2–5) | FINAL-state semantics: the final leg's before/after evidence (they measure resulting state, not process) |
     | scope violation (row 6) | UNION (OR) across all lifecycle legs |
     | repeated repair (row 7) | computed over the CONCATENATED signature stream of all legs, then reduced — the same signature once per leg IS a lifecycle repeat |
     | intervention (row 8) | UNION (OR) across all lifecycle legs |
     | cost (row 12) | SUM across all legs under provenance homogeneity (any leg unpriced under the basis ⇒ the trial's cost is insufficient, never partial) |
     | elapsed (row 13), where present | SUM across all legs, never silently one leg |
     | routing chain | ordered concatenation across the legs |
     Exact task × trial coverage — duplicate or missing folded
     entries REFUSE the report. The SAME fold semantics govern
     delegated `profile_sweep` cells, so cct_router and the
     fixed-profile controls compare identical units. Pinned
     discriminators: a provisional-leg intervention (or repeated
     repair) with a clean reconciliation still lowers the folded Q;
     the same repair signature once in each leg counts as a
     lifecycle repeat (a per-leg-reduce-then-OR mutation
     discriminates); the delegated task folds to ONE cell, not two.

4. **Evidence-set identity, discovery, and binding validation.** An
   evidence set is a directory containing the three artifacts (plus
   the ledger-relative evidence files records reference). Discovery
   walks operator-configured evidence roots (settings-owned, like the
   existing source roots; no default machine scan).
   - *Identity*: a fourth, EXTERNAL artifact — `manifest.json`
     (`benchmarks/schema/evidence-manifest.schema.json`), written
     LAST in staging — carries the full fingerprint, the sha256 of
     the canonical bytes of ALL THREE artifacts (report included —
     a schema-valid edit to report selections or figures must change
     the identity, since E2 deliberately recomputes nothing), and an
     `evidence_files` map (relative path → sha256) covering every
     evidence file the records reference. The set id is the sha256
     of the manifest's canonical bytes. Repeated runs with different
     outcomes get different ids; byte-identical republication is the
     same evidence and correctly the same id. Set ids, never
     filesystem paths, are what the API and every evidence reference
     speak; serving a referenced evidence file verifies its manifest
     hash before returning content.
   - *Binding validation*, pairwise and exact (routing-run records
     deliberately carry only the four shared fingerprint components —
     execution_identity is matrix-only by E1's design): the
     manifest's THREE artifact hashes against the actual bytes (read
     once, hash and parse the SAME bytes); the manifest's stored
     fingerprint EQUAL to the report's AND the matrix's full
     five-component fingerprint, and its shared four components
     equal to EVERY routing-run record's (a manifest whose
     fingerprint metadata is fabricated over genuine artifact bytes
     is `fingerprint_mismatch` — the pinned mutation); report ↔
     matrix on the FULL five-component fingerprint; runs ↔ report
     (and runs ↔ matrix) on the four shared components; the report's
     `source_artifacts` hashes as a redundant cross-check; every
     artifact against its schema (routing_eval.record_check,
     fail-closed). The discovered/served set id is ALWAYS
     recomputed as sha256(canonical manifest bytes) — the directory
     name is a convenience, never trusted.
   - *Failure vocabulary*, closed and SANITIZED: `missing_artifact`,
     `unreadable_artifact`, `schema_invalid`, `hash_mismatch`,
     `fingerprint_mismatch`, `path_escape` — each carrying the
     artifact enum and a sanitized detail (validator output stripped
     of filesystem paths; raw exceptions never serialized). Any
     failure makes the set `invalid_evidence`: SET-level, rendered
     with its code, never skipped, NO recommendation records derived.
     A regression runs the loader against a deliberately sensitive
     root pathname across all failure modes (missing, unreadable,
     malformed, hash-mismatched, escaping) and asserts no payload
     carries any path fragment.

5. **Recommendation derivation v1 — positive observed-evidence
   dominance, per (evidence set, task).** The unit is the task within
   one evidence set; trials are aggregated by E1's own pipeline (the
   report's per-task figures). Per task:
   - *actual*: the router's routing evidence as a closed structure —
     per trial: the ordered selected-profile chain, whether the task
     was delegated and reconciled — read from the routing-run
     records with decision indices as evidence refs. Display and
     evidence; never the recommendation trigger.
   - *candidates*: the EXECUTABLE control arms only — `always_best`
     and `always_cheapest`. The oracle is a hindsight bound, shown as
     the stated ceiling, never suggested (it is not a policy anyone
     can run).
   - *comparison tolerance* (declared once, used everywhere): E2
     declares its OWN absolute tolerance — two float64 figures are
     EQUAL iff they differ by at most `1e-9`, and *strictly greater*
     means exceeding by more than `1e-9`. (Attribution corrected
     from rev-3: E1's cost_reader uses
     `math.isclose(rel_tol=1e-9, abs_tol=1e-12)` for its value-bound
     check and the oracle sorts exact floats; E2 does not borrow
     those — this is E2's declared comparison rule, with boundary
     tests at the tolerance edge.) Both Q and cost comparisons use
     it; harmless rounding can never flip an outcome.
   - *the rule* (closed; positive evidence, never identity
     difference): a candidate arm is *dominating* for the task iff
     its per-task quality is strictly greater (per the tolerance)
     than the router's and its per-task cost under the declared basis
     is not greater — or its quality is equal (per the tolerance) and
     its cost strictly lower. `outcome = switch_profile` iff at least
     one candidate dominates (suggested = the dominating arm with the
     higher quality; ties between dominating arms break by lower
     cost, then arm name); `no_change_recommended` iff no candidate
     dominates and every consumed figure is present and sufficient —
     including when the router outperforms every control (the
     counterexample this rule exists for: configured-best is not
     observed-best, and identity difference alone recommends
     nothing); `insufficient_data` iff the set is VALID but any
     consumed figure is insufficient/withheld (arm insufficiency,
     withheld Q, withheld frontier, a task absent from an arm's
     table), carrying the specific insufficiency references. Invalid
     sets produce no records at all (decision 4).
   - *divergence*: the declared subtractions (router minus candidate
     per-task quality; router minus candidate per-task cost) of the
     report's served figures, computed in IEEE-754 float64.
   - *confidence*: a closed GRADE plus its basis, both required, and
     the grade measures the SAME claim the recommendation makes — per
     trial, the full tolerance-aware TWO-AXIS dominance predicate,
     not quality alone: for a `switch_profile` outcome, agreement =
     the fraction of trials in which the suggested arm's per-trial
     figures dominate the router's (quality strictly greater at cost
     not greater, or quality equal at cost strictly lower); for
     `no_change_recommended`, agreement = the fraction of trials in
     which NO candidate's per-trial figures dominate. A trial whose
     per-trial cost is unavailable under the declared basis cannot
     evaluate the predicate: the grade is capped at `low` and the
     basis names the unpriced trial as insufficient confidence
     evidence.
     Grade rule v2 (declared, deterministic): `high` iff declared
     trials ≥ 5 AND the full v1 component mask AND agreement ≥ 0.8
     AND every consumed trial evaluated the predicate; `moderate`
     iff trials ≥ 2 AND the full mask AND agreement ≥ 0.6 AND every
     trial evaluated; otherwise `low`. A single-outlier aggregate win
     with majority per-trial dominance failures therefore grades
     `low`, never `high` — the pinned regression for this rule. The basis names: declared
     trials, the agreement fraction, the divergence deltas with the
     cost basis, components_included, and the insufficiency
     references consumed (empty when none). Never a bare number.
   Derivation is deterministic: identical artifact bytes yield
   byte-identical recommendation records.

6. **Versioned recommendation record.**
   `benchmarks/schema/recommendation.schema.json` — schema_version 1,
   closed outcome vocabulary, evidence-reference shape, required
   confidence grade + basis fields, additionalProperties false.
   Derived records validate against it before serving (record_check).
   Evidence references are `{evidence_set_id, artifact:
   routing_runs|outcome_matrix|report, locator}` where locator is
   record indices / cell coordinates / arm+task keys / a RELATIVE
   ledger path for referenced evidence files. Absolute paths and any
   `..` segment are rejected at validation; resolution enforces
   containment under the set's root and regular-file-ness. No
   filesystem path — relative or otherwise — identifies a set; the
   opaque id does (finding: #261 prohibits sensitive absolute paths
   reaching the surface).

7. **No execution authority — enforced, not asserted.**
   Recommendations are derived at read time and served from the API;
   when cached, the cache lives under the analytics store only. The
   guard is executable, two ways: (a) E1's diff-guard test extends to
   this branch (production routing files byte-unchanged); (b) a new
   guard asserts no production routing script (`scripts/lib/routing-*`,
   `routing-cli.sh`, `cooldown-supervisor.sh`) references the
   recommendation schema, module, or storage paths, and that
   `session_analytics.routing_evidence` writes only under the
   analytics store.

8. **Redaction: consume-verbatim, prove the chain.** E1 artifacts are
   write-time-scrubbed; E2 renders them verbatim and derives prose
   only from figures and closed vocabularies, never from free text it
   composes out of un-scrubbed sources. The regression chains E1's
   boring-credential fixture (registry credential_env + echoed value)
   through evidence-set publication into the analytics API and
   asserts no payload carries the value; the API never serves the raw
   registry, any absolute path, or any file outside the evidence set.

9. **The figure-provenance gate (replacing "byte-equal", which JSON
   round-trips cannot honor).** Every numeric figure the API serves
   carries an exact source: a JSON-Pointer-style reference into one
   artifact, or a declared delta naming its two source pointers. The
   gate parses each artifact ONCE (canonical parse), resolves every
   pointer, and requires SEMANTIC equality of the parsed values
   (float64 equality after one canonical parse — no lexical byte
   comparison) for direct figures, and exact float64 equality with
   the recomputed subtraction for deltas. A served figure with no
   source pointer, an unresolvable pointer, or a value differing from
   its source fails the gate.

10. **Studio slice follows the benchmark-ui conventions — verified in
   a browser, not only by the compiler.** Typed fetcher in
   `studio/lib/api.ts` mirroring payloads exactly; a Routing tab in
   the `TABS` nav; `Card`/`Stat`/`useApi`,
   `Loading`/`ErrorNote`; explanatory empty state pointing at the E1
   scenario; the three recommendation outcomes visually distinct
   (insufficient-data never renders like no-change); no new npm
   dependencies; `npm run build` green.

11. **E2 adds no runtime authority (inherited from E1's decision 10).** No new
    key the router reads, no policy surface, no code path that
    changes a routing decision. Everything E2 adds is downstream of
    E1's artifacts, which are downstream of execution. This is what
    keeps the #109 acceptance box — "learned routing remains
    shadow-only until explicit calibration gates are met" — checked
    by construction, and it is proven the same way E1 proved it:
    routing suites pass unmodified, diff guard holds.

## Shadow-recommendation contract (normative)

| Field | Content | Source |
|---|---|---|
| `schema_version` | 1 | — |
| `evidence_set_id` | sha256 of the canonical `manifest.json` bytes (decision 4); always recomputed, never trusted from a directory name | manifest.json |
| `task_id` | the task | routing-run records |
| `actual` | closed per-trial structure: ordered selected-profile chain, delegated?, reconciled?; decision indices as refs | routing-run records |
| `suggested` | the dominating candidate arm + its per-task profile, or null; the oracle ceiling always named separately | report.json selections + per-task figures |
| `divergence` | per-task quality delta and cost delta (+ basis) vs each candidate, float64 subtraction of report figures | report.json per-task figures |
| `outcome` | `switch_profile` \| `no_change_recommended` \| `insufficient_data` | dominance rule, decision 5 |
| `confidence` | closed grade (`high`\|`moderate`\|`low`, decision 5 rule v2 incl. trial agreement) + basis: trials, agreement fraction, deltas + cost basis, components_included, consumed insufficiency refs | report.json |
| `evidence_refs` | `{evidence_set_id, artifact, locator}` per decision 6 — no absolute paths, no `..`, containment-checked | all three artifacts |

A recommendation with an unresolvable evidence reference is invalid.
`insufficient_data` requires at least one named insufficiency
reference and is derived only from VALID sets (invalid sets produce
set-level `invalid_evidence`, no records). No field is free prose.

## Files

| Path | Change |
| --- | --- |
| `benchmarks/schema/report.schema.json` | NEW — decision 3 (report contract v1) |
| `benchmarks/schema/evidence-manifest.schema.json` | NEW — decision 4 (set identity + full content binding) |
| `benchmarks/schema/recommendation.schema.json` | NEW — decision 6 |
| `scripts/benchmark_runner/routing_eval/routing_quality.py` | extend: report v1 additive fields (fingerprint, source bindings, selection provenance, per-task figures) + `write_report` |
| `scripts/benchmark_runner/routing_eval/scenario.py` (or a new `evidence_set.py`) | extend: `publish_evidence_set` orchestration (decision 2) incl. the production matrix sweep |
| `scripts/session_analytics/routing_evidence.py` | NEW — decisions 1, 4, 5: discovery, binding validation, derivation |
| `scripts/session_analytics/api/server.py` | extend: routing evidence + recommendation endpoints (set ids only) |
| `scripts/session_analytics/config.py` | extend: `AnalyticsConfig` evidence-roots field, defaults, layering (env/file precedence) |
| `scripts/session_analytics/cli.py`, `scripts/session_analytics/api/server.py` (`/api/settings`) | extend: evidence roots configured server-side; `/api/settings` exposes ONLY a sanitized shape (`{configured, root_count}` or opaque labels) — raw root paths never leave the server |
| `studio/lib/api.ts`, `studio/app/layout.tsx`, `studio/app/routing/page.tsx` | NEW tab — decision 10 |
| `tests/…` (session-analytics API tests), `scripts/benchmark_runner/tests/` | regressions per task list |
| `README.md`, `CHANGELOG.md`, `studio/README.md` | document the surface and the shadow contract |

## Verification

- Focused suites: routing_eval (write_report contract), session
  analytics API tests, derivation unit tests, studio `npm run build`.
- The verbatim gate, the authority guard, and the redaction chain are
  standing tests, not one-off checks.
- Decision-10 proof re-run at closure: routing shell suites unmodified
  at their pins + diff guard.
- Full CI-exact sweeps and origin-alignment refresh at closure, host
  baseline separated.
