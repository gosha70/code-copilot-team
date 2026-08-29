---
spec_mode: full
feature_id: routing-calibration
status: draft
date: 2026-08-29
risk_category: integration
justification: >
  Adds the #109 §12 calibration-gate machinery and a shadow-only
  similarity recommender over the E1/E2 contracts, including two
  LABELED E1 evidence additions (pre-routing task descriptors and the
  per-profile policy declarations) the metrics provably require: new
  versioned report schemas, deterministic derivation in session
  analytics, new read-only API endpoints, and a Studio surface.
  Integration risk across the analytics pipeline and Studio; zero
  runtime routing authority by construction, proven the same way E2
  proved it.
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

1. **Placement: session analytics, read-only over E1 sets via the E2
   loader — plus TWO labeled E1 evidence additions.** New module
   `session_analytics/routing_calibration.py` beside
   `routing_evidence.py`, consuming `load_evidence_sets` output only.
   E3 never opens an evidence file through any other path and never
   writes into an evidence root. The frozen artifacts do NOT carry two
   inputs the metrics provably require, so — per the "E1 change, not a
   workaround" rule — E1 gains two additions (decision 11): per-task
   PRE-ROUTING descriptors, and the per-profile policy declarations
   (capability tier, roles) of the executed registry. No other E1
   change is anticipated.

2. **The gate contract: five §12 conditions, executable, versioned.**
   `benchmarks/schema/calibration-report.schema.json`,
   `schema_version: 1`. Per gate: `{id, status:
   pass|fail|insufficient_data, measured, threshold, evidence_refs,
   reason}`; overall `calibrated = every gate pass`. The gates:
   - **G1 telemetry-complete**: over the corpus, the fraction of
     router records with measured (non-insufficient) cost AND verified
     effective-model identity; invalid_evidence sets are excluded from
     the corpus and their count reported beside it. Threshold:
     `min_sufficiency`.
   - **G2 labeled-volume**: counted over LABELED evidence only — a
     (set, task) pair counts iff its E2-derived label is DEFINED
     (outcome is not insufficient_data). Requires at least
     `min_tasks` distinct labeled tasks, each reaching `min_trials`
     trials WITHIN at least one single evidence set (trials never
     aggregate across sets — cross-set aggregation would mix
     fingerprints), across at least `min_sets` distinct contributing
     sets. A corpus whose labels are all insufficient_data cannot
     pass.
   - **G3 heldout-evaluated**: a CURRENT evaluation report exists —
     current means BOTH its `corpus_id` and its `policy_id`
     (decision 3) match the present corpus and configuration — and it
     covers at least `min_coverage` of the labeled corpus tasks.
   - **G4 false-downgrade**: the current evaluation report's
     false-downgrade rate (decision 7) is below
     `max_false_downgrade_rate`.
   - **G5 floors-authoritative**: structural, three conjuncts — (a)
     the operator's CURRENT effective policy (decision 8: tier floor
     AND the security/role policy source) parses and declares a tier
     floor; (b) the current evaluation report records zero
     floor-violating or policy-violating kNN recommendations (the
     recommender filters candidates against the CURRENT policy before
     ranking — decision 5; a violation reaching a report is a bug
     surfaced, never dropped); (c) the report's `policy_id` embeds the
     digest of that same policy, so a policy change stales every
     report (decision 3).
   A gate whose inputs do not exist (no evaluation report, empty or
   unlabeled corpus, stale report) is insufficient_data. Nothing
   anywhere auto-acts on a gate.

3. **Reports bind to corpus AND policy.**
   `corpus_id = sha256(canonical JSON of the sorted consumed set ids)`.
   `policy_id = sha256(canonical JSON of the full evaluation policy)`:
   the feature-vocabulary version, k, k_min, distance metric,
   weighting epsilon, normalization scheme, tier floor, the canonical
   digest of the current security/role policy source, and
   `max_false_downgrade_rate`. Evaluation and gate reports carry BOTH;
   serving recomputes both from the live corpus and configuration and
   marks any mismatch `stale: true` — a stale report renders with an
   explicit stale state and satisfies no gate. An evaluation produced
   under an old metric, floor, or policy can never pass G3–G5.

4. **Features are PRE-ROUTING only — the label's ingredients never
   enter the query vector.** The E2 truth label derives from the
   post-execution per-arm figures, so those figures (and any
   post-execution outcome: costs, quality, regressions, reconciliation
   state) are BANNED from the feature vocabulary. The closed,
   versioned feature vector per (set, task) uses only information
   available before routing, from the E1 additions (decision 11) and
   the records' pre-routing fields: the declared task class (§12's
   closed task-class vocabulary), the route class in force, the
   declared file-scope size, and the trial count as a corpus property.
   Labels remain E2's own derivation (`derive_recommendations` outcome
   + suggested arm) — single-source ground truth. Feature
   normalization is fitted on each training fold only (decision 6),
   never on the full corpus.

5. **The classifier is FULLY specified — two conforming
   implementations cannot disagree.**
   `knn-recommendation.schema.json` (v1) carries `outcome` (the E2
   closed trichotomy), `suggested` (arm+profile or null), `neighbors`
   (each: evidence_set_id, task, distance, label, evidence_refs), `k`,
   `distance_metric`, and the policy identity. The normative rules:
   - *Encoding*: categorical features (task class, route class)
     one-hot over their closed vocabularies; numeric features min-max
     normalized to [0,1] with bounds fitted on the training fold
     (query values clamped into [0,1]).
   - *Missing values*: a (set, task) lacking any required feature or a
     defined label is EXCLUDED from the neighbor pool and, as a query,
     is `insufficient_data` with the missing field named — no
     imputation, ever.
   - *Distance*: L2 over the encoded vector (`distance_metric:
     "l2_v1"`; changing it is a policy change via decision 3).
   - *Candidate filtering BEFORE ranking*: neighbors whose labeled
     suggestion names a profile that is absent from the CURRENT
     policy's declarations, below the tier floor, or ineligible under
     the current security/role policy are removed before any distance
     ranking (decision 8 defines the policy source).
   - *Neighborhood*: the `min(k, available)` nearest survivors; if
     fewer than `k_min` survive, the recommendation is
     `insufficient_data`.
   - *Vote*: distance-weighted, weight `1/(distance + epsilon)`
     (epsilon from config), summed per outcome label.
   - *Ties and resolution*: equal weight sums resolve CONSERVATIVELY
     to `no_change_recommended` (a tie never produces a switch). If
     `switch_profile` wins, the suggested (arm, profile) is the
     highest-weight switch-voting neighbor's suggestion (ties by
     smaller distance, then set id, then task id); if that profile
     fails the current-policy filter (registry drift between sets),
     the result is `insufficient_data`, never a substitution.
   - *Determinism*: identical corpus bytes + identical policy ⇒
     byte-identical output.
   The kNN output renders BESIDE the E2 recommendation, clearly
   labeled, and never replaces or reweights it.

6. **Held-out evaluation: leave-one-task-out, leakage-free, durable.**
   For every labeled corpus task: remove ALL of that task's records
   and cells from the neighbor pool (across every set), fit
   normalization bounds on the REMAINING pool (per fold), predict,
   compare to the E2 truth. `evaluation-report.schema.json` (v1): the
   split definition, per-task `{predicted, truth, downgrade_flag}`,
   aggregate agreement, the false-downgrade numerator/denominator/
   rate, the `unevaluable` count, `corpus_id`, `policy_id`, and the
   full policy echo. Written atomically (tmp + rename +
   pre-rename schema validation) into the analytics-owned
   `routing_calibration_root` — never into an E1 evidence root.

7. **False downgrade, exactly — against the SAFETY BASELINE tier.**
   The baseline tier for a held-out task is: the tier of the TRUTH's
   suggested profile when truth is `switch_profile`; the tier of the
   router's ACTUAL selection when truth is `no_change_recommended`
   (tiers resolved from the set's persisted profile-policy
   declarations, decision 11). A prediction counts as a false
   downgrade iff it is `switch_profile` to a profile of a LOWER tier
   than that baseline. So kNN predicting Tier 2 while truth switches
   within Tier 1 IS a false downgrade. Tasks whose truth is
   `insufficient_data` are excluded from the denominator and counted
   as `unevaluable`. The rate is `false_downgrades / evaluated`, with
   numerator, denominator, and exclusions all reported.

8. **Configuration, not constants — including the policy source.**
   New keys through the existing layering (`config_data/defaults.json`
   < user config < env): `routing_calibration_root`, gate thresholds
   (`min_sufficiency`, `min_tasks`, `min_trials`, `min_sets`,
   `min_coverage`, `max_false_downgrade_rate`), classifier parameters
   (`k`, `k_min`, `distance_metric`, `vote_epsilon`), `tier_floor`,
   and `policy_source` — the path of the operator's CURRENT routing
   policy declarations (the registry file or an exported policy
   document) from which per-profile tier/role/security eligibility is
   read and whose canonical digest enters `policy_id`. No default
   value lives in Python source; the policy source is read, never
   written.

9. **No execution authority — proven, not asserted.** No production
   routing script references `routing_calibration`, its schemas, or
   its config keys; the standing E2 authority-guard test extends to
   every new module; E3 writes only under `routing_calibration_root`;
   routing shell suites pass unmodified at their pins and the
   production-file diff guard holds at closure. Serving follows the
   E2 sanitization floor (FR-E3-7); the `policy_source` path itself is
   configuration and is never serialized into a payload.

10. **API + Studio surface.** Endpoints:
    `GET /api/routing/calibration` (the current gate report, or
    insufficient_data when none, with the stale state explicit),
    `GET /api/routing/calibration/evaluation` (the current evaluation
    report, stale-flagged), and the kNN recommendations served beside
    the E2 recommendations for a set/task. Studio: a Calibration panel
    on the Routing tab (per-gate status with measured/threshold/
    evidence, overall verdict, stale banner) and a labeled kNN section
    in the recommendation cards with openable neighbors.
    Browser-verified against live fixtures at desktop and mobile
    widths for: no-data, insufficient, gates-mixed, gates-all-pass,
    and stale (corpus-changed AND policy-changed) states. No new npm
    dependencies.

11. **The two labeled E1 evidence additions.** Published evidence sets
    gain two manifest-bound, schema'd, scrubbed-at-write artifacts,
    derived at publication from the SAME sources the set already
    binds:
    - `task-descriptors.json`: per task — the declared §12 task class
      (closed vocabulary: one-file, multi-file feature, refactor,
      reproduced bug, integration, negative control), the route class
      in force, and the declared file-scope size; derived from the
      executed scenario configuration (bound by `preset_digest`).
    - `profile-policy.json`: per profile of the executed registry —
      `capability_tier` and roles; derived from the executed registry
      at publication (bound by `registry_digest`).
    Both are validated in staging, hashed into `manifest.artifacts`,
    covered by `validate_evidence_set`'s binding checks, and served
    through the E2 artifact surface (their locators become
    followable). Sets published before this addition lack them: E3
    treats such sets as UNLABELED for features/tiers (their tasks are
    `insufficient_data` as queries and excluded from pools/G2) —
    never guessed at. Existing E1 metric definitions, selectors, and
    report semantics are untouched.

## Files

- `benchmarks/schema/calibration-report.schema.json` — new (decision 2)
- `benchmarks/schema/evaluation-report.schema.json` — new (decision 6)
- `benchmarks/schema/knn-recommendation.schema.json` — new (decision 5)
- `benchmarks/schema/task-descriptors.schema.json`,
  `benchmarks/schema/profile-policy.schema.json` — new (decision 11)
- `scripts/benchmark_runner/routing_eval/evidence_set.py` — the labeled
  E1 publication/validation additions (decision 11)
- `scripts/session_analytics/routing_calibration.py` — new
  (decisions 1–9)
- `scripts/session_analytics/config.py` / `constants.py` /
  `config_data/defaults.json` — config keys (decision 8)
- `scripts/session_analytics/api/server.py` — routes (decision 10)
- `scripts/session_analytics/tests/test_routing_calibration.py` — new
- `scripts/benchmark_runner/tests/test_routing_eval_evidence_set.py` —
  the decision-11 binding regressions
- `scripts/session_analytics/tests/test_api.py` — CI-gated routes
- `studio/lib/api.ts`, `studio/app/routing/*` — surface (decision 10)
- Docs at closure: `README.md`, `CHANGELOG.md`,
  `scripts/session_analytics/README.md`, `studio/README.md`

## Verification

- Leakage: a mutation that (a) leaves the held-out task's records in
  the neighbor pool, OR (b) adds a post-execution figure to the
  feature vector, OR (c) fits normalization on the full corpus, must
  each be discriminated by a pinned regression.
- Determinism: identical corpus + policy ⇒ byte-identical kNN output,
  gate report, and evaluation report; every classifier rule in
  decision 5 (encoding, filtering order, k_min, vote weights,
  conservative tie, suggestion resolution) carries a discriminating
  regression or mutation.
- Currentness: corpus change, k/metric/floor change, and
  policy-source change each stale every report (pinned per
  dimension); a stale report satisfies no gate.
- False-downgrade arithmetic pinned against a hand-computed fixture
  covering BOTH baseline branches of decision 7; the tier-resolution
  and truth-exclusion rules each carry a discriminating mutation.
- G2 cannot pass on an unlabeled corpus (pinned).
- Decision-11 artifacts: publication/validation binding regressions in
  the E1 suite (missing, tampered, orphaned, pre-addition sets);
  existing E1 suites stay green.
- insufficient_data never collapses; authority guard extended and
  green; routing shell suites at pins; diff guard vs master empty at
  closure; full component sweeps with host baseline separated; Studio
  states browser-verified at 1440/375 with rendered assertions.

## Increment boundary

Promotion of learned routing to any authority is OUT. When the gates
hold, a future increment — separate issue, owner-initiated — may
propose it; this plan deliberately contains no mechanism that could
act on a gate result.
