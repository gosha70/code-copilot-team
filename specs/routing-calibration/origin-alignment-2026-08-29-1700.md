# Origin alignment — routing-calibration (E3 of #109, issue #266)

## Origin capture (2026-08-29)

The origin is issue #266, itself derived from #109 §12 (the five
calibration conditions, "initially in shadow mode") and #109 Delivery
Plan Increment E bullet 5 — the last unshipped E bullet after E1
(#260) and E2 (#261) merged. The owner's directive: "Continue to the
next phase of #109" (2026-08-29, after PR #265 merged).

Scope mapping, origin → bundle:

- §12 condition "telemetry complete and accurate" → gate G1
  (plan decision 2).
- §12 "enough repeated labeled runs" → G2.
- §12 "recommendations evaluated against held-out tasks" → G3 + the
  leave-one-task-out evaluation (decisions 6–7).
- §12 "false downgrades to Tier 2 below an explicit safety
  threshold" → G4 with the exact false-downgrade definition
  (decision 7).
- §12 "operator-configured security and tier floors remain
  authoritative" → G5, structural (decision 2) + floor filtering
  before ranking (decision 5).
- "initially in shadow mode" + the umbrella acceptance box → the
  increment boundary: no execution authority, no gate-triggered
  action, promotion is a future owner-initiated increment.

Explicitly out of scope, from the issue's non-goals: promotion,
automatic actions, online learning/embeddings, new E1 metrics (the
"E1 change, not an E3 workaround" rule carries over).

## Plan review round 1 (owner, on 37eb24a) — five P1 + two P2, applied

The single correction pass under the anti-ping-pong rule; all seven
findings verified against the schemas/registry before editing.

1. **[P1] Target leakage removed** (decisions 4–6): the E2 truth label
   derives from the post-execution per-arm figures, so those figures —
   and every post-execution outcome — are now BANNED from the feature
   vocabulary; features are pre-routing only, and normalization is
   fitted per training fold. Confirmed in-tree that the frozen records
   carry only `route_class` pre-routing → the required task
   descriptors are a DECLARED labeled E1 change (decision 11), exactly
   as the finding prescribed.
2. **[P1] Currentness binds policy, not just corpus** (decision 3):
   `policy_id` — canonical digest over the full evaluation policy
   including feature version, classifier parameters, normalization,
   tier floor, and the current security/role policy-source digest —
   joins `corpus_id` on every report; either mismatch stales the
   report and no stale report satisfies a gate.
3. **[P1] The tier mapping is persisted, source-bound** (decision 11):
   confirmed the frozen artifacts carry only the opaque
   `registry_digest` — `profile-policy.json` (per-profile
   capability_tier + roles, derived from the executed registry at
   publication) becomes a manifest-bound evidence artifact; the
   false-downgrade metric resolves tiers from it, never from a guess.
4. **[P1] The security half of the floor gate restored** (decisions 2,
   5, 8): `policy_source` names the operator's CURRENT policy
   declarations; the recommender filters candidates against tier AND
   security/role eligibility BEFORE ranking; G5 gains three conjuncts
   including the policy-digest binding, so historical admissibility
   can never substitute for current policy.
5. **[P1] False-downgrade baseline corrected** (decision 7): the
   safety baseline is the TRUTH's suggested tier when truth recommends
   a switch (so predicting Tier 2 while truth switches within Tier 1
   COUNTS), and the router's actual tier when truth recommends no
   change; both branches pinned in the verification list.
6. **[P2] The classifier is fully normative** (decision 5): one-hot
   encoding over closed vocabularies, missing-value refusal (no
   imputation), fold-fitted min-max normalization with clamping,
   l2_v1, filter-before-rank, min(k, available) with k_min refusal,
   distance-weighted vote with configured epsilon, conservative tie
   to no_change, highest-weight-neighbor suggestion resolution with
   the current-policy-miss → insufficient_data rule.
7. **[P2] G2 counts labeled evidence** (decision 2): only (set, task)
   pairs with a DEFINED E2 label count; trials must repeat within a
   single set (never aggregated across fingerprints); an all-
   insufficient corpus cannot pass.

spec.md (FR-E3-2/3/4, constraints, non-goals) and tasks.md (T1–T3)
updated to reference the corrected decisions; the two labeled E1
additions moved from "none anticipated" to declared scope.

## Plan review round 2 (owner, on 8d69e33) — APPROVED

The reviewer verified all seven rev-2 corrections against the tree
independently and re-ran the gates (spec 2/0, origin aligned/high,
whitespace clean, no restatement drift). No P0/P1 blockers; plan
status flipped to `approved`; T1–T5 clear to proceed.

Carried forward, explicitly non-blocking (P3, for the FUTURE
promotion increment's spec, not E3): "trial count as a corpus
property" is well-defined for shadow evaluation over published sets
but would be undefined for a live pre-routing query; if learned
routing is ever proposed for authority, that is a feature-vocabulary
revision — a `policy_id`-bumping change exactly as decision 3
anticipates.

## T1 build (2026-08-29) — schemas, identities, configuration, E1 additions

Built per decisions 2, 3, 5, 6, 8, 11:

- **Five schemas** (`calibration-report`, `evaluation-report`,
  `knn-recommendation`, `task-descriptors`, `profile-policy`), all
  within the in-repo validator subset; the evidence-manifest schema
  gains the two OPTIONAL artifact hash keys.
- **The labeled E1 additions** (decision 11): the scenario config
  gains an optional, closed, coverage-complete `task_descriptors`
  table (closed §12 class vocabulary; every declared task described
  or none; undeclared tasks refused); `derive_task_descriptors`
  derives route classes STRUCTURALLY from the config's own
  membership declarations (tier1_only → tier1_only, delegate →
  tier2_preferred — the class the delegation seam records, verified
  in-tree); `derive_profile_policy` reads the executed registry
  through the production parser and refuses a profile without a
  declared capability_tier. `_publish` writes both as canonical JSON
  hashed into `manifest.artifacts`; `validate_evidence_set` binds a
  PRESENT key fully (exists, hash, schema, digest agreement with the
  manifest fingerprint, exact coverage: descriptor tasks within the
  matrix; every executed profile in the policy) and loads an ABSENT
  key as None — pre-addition sets stay valid and unlabeled. The
  production `publish_evidence_set` derives both; the LIVE arc test
  pins that the published set carries the profile policy and no
  fabricated descriptors, and byte-identical republication stays
  idempotent WITH the additions (the live suite caught the
  republication call sites omitting them — fixed by carrying the
  validated docs through).
- **Identities** (decision 3): `corpus_id` over valid set ids only;
  `EvaluationPolicy` + `policy_id` over the full policy document;
  `report_staleness` names its reasons per dimension.
- **Configuration** (decision 8): ONE nested `routing_calibration`
  block through the standard layering with per-key
  `CCT_SA_CALIBRATION_<KEY>` env overrides coerced to the defaults
  file's types; `policy_from_config` REFUSES a missing key
  (CalibrationError) — no value is ever completed from code; the
  defaults file ships every key (pinned).
- **Regressions**: E1 binding set (published-additions bind+load;
  pre-addition unlabeled; tampered bytes → hash_mismatch; preset
  binding → fingerprint_mismatch; unknown task / missing executed
  profile → reference_mismatch; missing bound artifact →
  missing_artifact), scenario-config descriptor validation (closed
  keys, closed classes, omission, undeclared task), corpus identity
  (order-free, add/remove/invalidate, invalid exclusion), policy
  identity (all ten dimensions change it, no collisions),
  policy-source digest byte-tracking, staleness per dimension,
  config layering + env coercion, schema inverse tests for every new
  closed vocabulary.
- **Mutations (all discriminated)**: optional-artifact binding
  disabled (6 failures); corpus_id counting invalid sets; policy_id
  dropping tier_floor. Restores verified byte-identical.

Suites: session-analytics discovery 349 OK (35 CI-gated skips); E1
evidence_set 20/20 including the live arc (with the new pins),
quality + redaction green.

## Verdict

Verdict: aligned
Confidence: high

The bundle covers exactly the five §12 conditions and the shadow kNN
bullet, nothing more; the single addition beyond §12's literal text —
corpus-bound staleness (decision 3) — exists so a gate can never pass
against evidence it was not computed from, which is the §12 intent
("evaluated against held-out tasks" of the actual corpus). Plan
status: draft, pending owner review.
