---
spec_mode: full
feature_id: routing-calibration
status: draft
date: 2026-08-29
risk_category: integration
justification: >
  Adds the #109 §12 calibration-gate machinery and a shadow-only
  similarity recommender over the frozen E1/E2 contracts: new versioned
  report schemas, deterministic derivation in session analytics, new
  read-only API endpoints, and a Studio surface. Integration risk across
  the analytics pipeline and Studio; zero runtime routing authority by
  construction, proven the same way E2 proved it.
origin:
  type: issue
  issue: 266
  parent: 109
  references:
    - "#266 issue body — the E3 scope, the five gates, shadow-only kNN, held-out evaluation, acceptance list, and non-goals"
    - "#109 §12 Benchmark-driven evolution — the five calibration conditions verbatim, and 'initially in shadow mode'"
    - "#109 §Delivery Plan Increment E bullet 5 — 'Optional similarity/kNN policy only after calibration' (the last unshipped E bullet)"
    - "#109 Acceptance §Evaluation and observability — 'Learned routing remains shadow-only until explicit calibration gates are met'"
    - "specs/routing-shadow/ — E2's frozen consumption contracts: load_evidence_sets validation, the recommendation record, the provenance/authority/sanitization gates E3 inherits as a floor"
    - "specs/routing-eval/ — E1's frozen evidence contract (routing-run, outcome-matrix, report, manifest schemas; set-atomic publication)"
---

# Plan: calibration gates + shadow kNN recommender (E3 of #109)

## Decisions

1. **Placement: everything lives in session analytics, read-only over
   E1 sets via the E2 loader.** New module
   `session_analytics/routing_calibration.py` (derivation + gates +
   evaluation) beside `routing_evidence.py`, consuming
   `load_evidence_sets` output only — the same validated,
   write-time-redacted artifacts E2 consumes. E3 never opens an
   evidence file through any other path and never writes into an
   evidence root. Anticipated E1 changes: none; if a needed measure is
   missing, that is an E1 change (labeled), not a workaround here.

2. **The gate contract: five §12 conditions, executable, versioned.**
   `benchmarks/schema/calibration-report.schema.json`, `schema_version: 1`.
   Per gate: `{id, status: pass|fail|insufficient_data, measured,
   threshold, evidence_refs, reason}`; overall
   `calibrated = every gate pass`. The gates:
   - **G1 telemetry-complete**: over the corpus, the fraction of
     router records with measured (non-insufficient) cost AND
     verified effective-model identity, and the count of
     invalid_evidence sets (must be zero among consumed sets — invalid
     sets are excluded from the corpus and reported). Threshold:
     minimum sufficiency fraction.
   - **G2 labeled-volume**: at least `min_tasks` distinct tasks with at
     least `min_trials` trials each, across at least `min_sets`
     evidence sets.
   - **G3 heldout-evaluated**: a current (corpus-bound, decision 3)
     evaluation report exists covering at least `min_coverage` of the
     corpus tasks.
   - **G4 false-downgrade**: the evaluation report's false-downgrade
     rate (decision 7) is below `max_false_downgrade_rate`.
   - **G5 floors-authoritative**: structural, two conjuncts — the
     operator's floor configuration parses and declares at least a tier
     floor, AND the current evaluation report records zero
     floor-violating kNN recommendations (the recommender filters
     candidates below the declared floors BEFORE ranking; a violation
     reaching a report is a bug surfaced, never dropped).
   A gate whose inputs do not exist (no evaluation report, empty
   corpus) is insufficient_data. Nothing anywhere auto-acts on a gate.

3. **Corpus identity binds every report.**
   `corpus_id = sha256(canonical JSON of the sorted consumed set ids)`.
   Gate and evaluation reports carry it; serving recomputes the current
   corpus and marks a report `stale: true` when ids differ — a stale
   report renders with an explicit stale state, never as current.
   Invalid sets are never part of the corpus; their presence is
   reported beside it.

4. **Features and labels are declared, closed, and derived from served
   figures only.** Per (set, task): the feature vector is a fixed,
   versioned list — route class and delegation flags from the router
   records; per-arm per-task quality and cost figures from the report;
   trial count. Labels come from E2's OWN derivation
   (`derive_recommendations` outcome + suggested arm) — the ground
   truth for "what routing would have been better" stays single-source.
   No feature is recomputed from raw measures E1/E2 already serve.

5. **kNN is deterministic and provenance-carrying.**
   `knn-recommendation.schema.json` (v1): per queried task —
   `outcome` (the E2 closed trichotomy, same vocabulary), `suggested`
   (arm+profile or null), `neighbors` (each: evidence_set_id, task,
   distance, label outcome, evidence_refs into that set), `k`,
   `distance_metric` (declared name), and `insufficient_data` whenever
   fewer than `k_min` labeled neighbors exist after floor filtering.
   Distance: normalized L2 over the declared numeric features (the
   metric name is versioned config; changing it is a contract change).
   Determinism: identical corpus bytes ⇒ byte-identical output (ties
   broken by set id, then task id). The kNN output is rendered BESIDE
   the E2 recommendation and never replaces or reweights it.

6. **Held-out evaluation: leave-one-task-out, leakage-free, durable.**
   For every corpus task with a defined E2 label: remove ALL of that
   task's trials/records from the neighbor pool (across every set),
   predict with the remaining corpus, compare to the E2-derived truth.
   `evaluation-report.schema.json` (v1): the split definition, per-task
   `{predicted, truth, downgrade_flags}`, aggregate agreement, the
   false-downgrade rate, corpus_id, and the config (k, metric,
   thresholds) it ran under. Written atomically
   (tmp + rename) into the analytics-owned output root
   (`routing_calibration_root`, config decision 8) — never into an E1
   evidence root; the file is schema-validated before rename.
7. **False downgrade, exactly.** A held-out task counts as a false
   downgrade iff the kNN prediction is `switch_profile` to a profile of
   a LOWER capability tier than the router's actual selection for that
   task (tier comparison per the registry declarations already carried
   in the evidence), while the E2 truth for that task is
   `no_change_recommended`. Tasks whose truth is `insufficient_data`
   are excluded from the denominator and counted separately as
   `unevaluable`. The rate is `false_downgrades / evaluated`; the
   report carries numerator, denominator, and the excluded count.

8. **Configuration, not constants.** New keys through the existing
   session-analytics layering (`config_data/defaults.json` < user
   config < env): `routing_calibration_root`, gate thresholds
   (`min_sufficiency`, `min_tasks`, `min_trials`, `min_sets`,
   `min_coverage`, `max_false_downgrade_rate`), kNN parameters
   (`k`, `k_min`, `distance_metric`), and the floor declaration
   (`tier_floor`). No default value lives in Python source.

9. **No execution authority — proven, not asserted.** The E2 authority
   guard test extends: no production routing script references
   `routing_calibration`, its schemas, or its config keys; E3 writes
   only under `routing_calibration_root`; routing shell suites pass
   unmodified at their pins and the production-file diff guard holds at
   closure. Serving follows the E2 sanitization floor (FR-E3-7).

10. **API + Studio surface.** Endpoints:
    `GET /api/routing/calibration` (the current gate report, or
    insufficient_data when none/stale),
    `GET /api/routing/calibration/evaluation` (the current evaluation
    report, stale-flagged), and the kNN recommendations served beside
    the E2 recommendations for a set/task (same sanitized boundary).
    Studio: a Calibration panel on the Routing tab (per-gate status
    with measured/threshold/evidence, overall verdict, stale banner)
    and a labeled kNN column/section in the recommendation cards with
    openable neighbors. Browser-verified against live fixtures at
    desktop and mobile widths for: no-data, insufficient, gates-mixed,
    gates-all-pass, and stale states. No new npm dependencies.

## Files

- `benchmarks/schema/calibration-report.schema.json` — new (decision 2)
- `benchmarks/schema/evaluation-report.schema.json` — new (decision 6)
- `benchmarks/schema/knn-recommendation.schema.json` — new (decision 5)
- `scripts/session_analytics/routing_calibration.py` — new (decisions 1–9)
- `scripts/session_analytics/config.py` / `constants.py` /
  `config_data/defaults.json` — config keys (decision 8)
- `scripts/session_analytics/api/server.py` — routes (decision 10)
- `scripts/session_analytics/tests/test_routing_calibration.py` — new
- `scripts/session_analytics/tests/test_api.py` — CI-gated routes
- `studio/lib/api.ts`, `studio/app/routing/*` — surface (decision 10)
- Docs at closure: `README.md`, `CHANGELOG.md`,
  `scripts/session_analytics/README.md`, `studio/README.md`

## Verification

- Determinism: identical corpus ⇒ byte-identical kNN output, gate
  report, and evaluation report (modulo corpus_id which IS the
  identity).
- Leakage: a mutation that leaves the held-out task's records in the
  neighbor pool must be discriminated by a pinned regression.
- insufficient_data never collapses: thin corpus, missing evaluation
  report, and stale corpus each pin their explicit state.
- False-downgrade arithmetic pinned against a hand-computed fixture;
  the tier-comparison and truth-exclusion rules each carry a
  discriminating mutation.
- Authority guard extended and green; routing shell suites at pins;
  diff guard vs master empty at closure; full component sweeps with
  host baseline separated.
- Studio states browser-verified at 1440/375 with rendered assertions.

## Increment boundary

Promotion of learned routing to any authority is OUT. When the gates
hold, a future increment — separate issue, owner-initiated — may
propose it; this plan deliberately contains no mechanism that could
act on a gate result.
