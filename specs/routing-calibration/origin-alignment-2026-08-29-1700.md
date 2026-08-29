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

## T1 review round 1 (owner, on 75dccb1) — APPROVED, GO T2

The reviewer verified the build directly (ran the suites in their own
container — matching counts — and read the derivations, bindings,
identities, and config refusals in-tree). No P0/P1 findings. Two P3s
carried and APPLIED at the start of T2: the decision-3 comment on why
`policy_from_config` excludes the `min_*` gate thresholds (gates
apply them live; they never stale reports), and `_coerce_like`'s
uncoercible-override error now names the offending env key.

## T2 build (2026-08-29) — features, labels, and the kNN recommender

Built per decisions 4–5 (+ the serving-parity rule):

- **Extraction** (`extract_examples`): features ONLY from the
  persisted descriptors + the E2-derived trial count; labels ONLY
  from `derive_recommendations` (defined iff outcome is not
  insufficient_data); a set without descriptors (or a task without
  one) yields feature-less examples with the reason named — refusal,
  never imputation.
- **The closed vocabulary pin**: `FEATURE_NAMES` (6 task-class
  one-hots + 4 route-class one-hots + file_scope + trial_count) is
  asserted VERBATIM in a regression — a post-execution figure can
  only enter by changing the tuple, which is a feature-vocabulary
  policy change.
- **The classifier** (`knn_recommendation`): every decision-5 rule as
  specified — one-hot encoding, fold-fitted min-max with clamping
  (degenerate min==max features normalize to 0.0, the one
  implementation-level determinization, recorded here for review),
  l2, current-policy filtering BEFORE ranking
  (`_eligible_under_policy`: profile present in the CURRENT
  declarations, at/above the tier floor, and carrying the `build`
  role — the concrete role conjunct, recorded here for review),
  min(k, available) with k_min refusal, 1/(d+ε) weighted voting,
  conservative ties to no_change, winner resolution by
  (weight, distance, set id, task id) with the current-policy-miss →
  insufficient_data belt. Schema-validated before return.
- **Serving parity with LOTO** (recorded normative choice): the
  neighbor pool excludes EVERY example of the queried task — a
  same-task example's label derives from that task's own figures, so
  letting it vote would be self-matching leakage at serving time.
- **Current policy source** (`load_current_policy`): read through the
  E1 production parser; absent, unreadable, or validator-refused
  sources are None (insufficient_data downstream), never fabricated —
  the validator-refusal path was caught by a test and widened to
  `ControlSetIncomplete` honestly.
- **Regressions** (25 → 29 tests): vocabulary pin; extraction;
  missing-descriptor refusal both as pool member and as query;
  byte-identical output under corpus reordering; switch majority;
  k_min insufficiency; no-current-policy refusal; same-task
  exclusion; filter-before-ranking (nearest-ineligible fixture);
  role/tier/absent-profile eligibility table; conservative tie;
  HAND-COMPUTED distances and outcome (bounds [1,8], query clamped,
  distances 0, 6/7, 1 — computed on paper, not a golden from the
  implementation); neighbor refs resolve pointer-by-pointer against
  the served report; schema validity; policy-source parsing.
- **Mutations (all discriminated)**: full-corpus normalization
  (bounds include the query); a post-execution figure
  (quality_delta) leaking into the vector; filter moved after
  ranking; tie resolving to switch; unweighted voting. Restores
  byte-identical.

Suites: session-analytics discovery 365 OK (35 CI-gated skips).

## T2 review round 1 (owner, on 1ef2316) — one P1 + two P2, applied

The single correction pass. All three verified in-tree first.

1. **[P1] `trial_count` now reads the DECLARED count.** The reviewer
   traced that `rec["confidence"]["basis"]["trials"]` is
   `max(len(actual["per_trial"]), 1)` — an execution OBSERVATION, not
   a pre-routing corpus property — and that the T2 mutation battery
   could not see it, because the feature name was already blessed in
   `FEATURE_NAMES` (mutation (b) only catches an UNBLESSED figure).
   Resolution (a), the reviewer's preference: the scenario's declared
   `trials` now rides in `task-descriptors.json` (schema-required,
   preset-digest-bound, refused at derivation when the scenario
   declares none), and `extract_examples` reads it from the artifact;
   a descriptors artifact without it yields feature-less examples.
   THREE regressions pin it: declared-vs-observed divergence (5
   declared / 1 recorded, with the observed value asserted to differ
   so a record-sourced implementation cannot pass), declared trials
   changing neighbor ORDERING (the source is load-bearing, not
   cosmetic), and missing-declared-trials refusal. New mutation
   (b2) — source the blessed feature from the observation — fails 2
   tests. Plan decision 4 and decision 11 reworded to name the
   declared count explicitly (precision within the approved decision,
   not an amendment); the Verification list gains (b2) and the
   normalization-parity item.
2. **[P2] `tier_floor` is a closed vocabulary** validated where the
   policy is assembled: `"Tier1"`, `"tier3"`, `""`, `"TIER2"` refuse
   with `CalibrationError` naming the field, instead of a bare
   `KeyError` surfacing from inside recommendation at the T4 API
   boundary. Mutation (check removed) discriminated.
3. **[P2] Neighbor `evidence_refs` are E2-shaped.** The synthesized
   slash-path strings are gone: each neighbor carries its own E2
   record's refs verbatim (the closed `{evidence_set_id, artifact,
   locator}` shape, `$ref`'d into the kNN schema from
   recommendation.schema.json), so the T4 card resolves both sources
   through ONE resolver and the refs are no longer narrowed to
   `cct_router`. The regression asserts the E2 shape, per-locator
   resolution, and that non-router arms are covered. Mutation
   (narrowed synthesized ref) discriminated.

Carried to T3 (recorded in tasks.md): `_fit_bounds` fits on the
ELIGIBILITY-FILTERED pool, so LOTO must filter identically or the
measured false-downgrade rate would not describe serving behaviour —
pinned with a filtered-vs-unfiltered mutation beside leakage (a).

Non-blocking P3s acknowledged, no action this round: the shipped
`tier_floor: "tier1"` default makes tier2 profiles ineligible (a
sentence for the T5 operator docs), and `_encode`/`_l2` recompute per
neighbor (deterministic, irrelevant at corpus scale).

Suites after the pass: calibration 31 OK, E1 calibration-additions
9/9, session-analytics discovery 369 OK (35 CI-gated skips).

## T2 review round 2 (owner, on f0e0ac8) — APPROVED, GO T3

The reviewer verified the schema `$ref` actually resolves (the in-repo
validator RAISES on unimplemented keywords rather than skipping, so
the constraint is real), confirmed `$defs/evidence_ref` is byte-for-
byte E2's own definition, and reproduced the suites. Classification
question settled: the trial-count change is PRECISION, not amendment
— it narrows decision 4 to the single reading it always intended and
permits nothing new; resolution (b) would have loosened the leakage
ban and needed justification. One P3 (a defensive branch naming the
wrong missing field) fixed at the start of T3.

## T3 build (2026-08-29) — held-out evaluation and the five gates

Built per decisions 2, 6, 7:

- **LOTO evaluation** (`evaluate_heldout`): every labeled (set, task)
  is predicted with EVERY example of that task absent from the
  neighbor pool. The fold reuses `knn_recommendation` rather than
  reimplementing exclusion, so serving and evaluation cannot drift —
  one rule, one implementation, and normalization parity with serving
  follows by construction (the carried T2 review item).
- **The downgrade arithmetic** (decision 7, both branches):
  `baseline_tier` returns the TRUTH's suggested tier when truth
  switches (so a tier-2 prediction against a within-tier-1 truth
  switch counts) and the tier the router actually operated at when
  truth keeps. Recorded determination for review: a chain can name
  several profiles, so the actual-branch baseline is the LOWEST tier
  the router actually used — recommending a tier the router already
  ran at is not a downgrade. Unresolvable tiers count neither way.
  Truths that are insufficient_data are excluded from the denominator
  and counted as `unevaluable`.
- **Durable reports**: schema-validated BEFORE the rename, written
  atomically into the analytics-owned calibration root (never an
  evidence root); an absent, unreadable, or invalid report loads as
  None so gates report insufficient_data rather than partial trust.
- **The five gates** (`compute_gates`): G1 measures cost +
  VERIFIED effective-model identity per record (null means
  unverified, never assumed); G2 counts only DEFINED labels with
  trials repeating WITHIN a single set — recorded distinction: the
  gate counts OBSERVED runs (a volume gate measures what actually
  happened) while features may read only the DECLARED count, the
  mirror image of the T2 round-1 rule; G3/G4 consume only a CURRENT
  report (corpus_id AND policy_id both matching); G5 evaluates its
  three conjuncts with violations SURFACED, never dropped. Missing
  thresholds refuse rather than defaulting. Nothing acts on a result.
- **Mutations — six, all discriminated**: leakage (a) held-out task
  left in the pool (4 failures); bounds fitted on the UNFILTERED
  pool; the truth-switch baseline branch removed; insufficient truths
  counted in the denominator; floor violations dropped from G5;
  staleness ignored by the gates.
- **Honesty note**: two of those six initially did NOT discriminate,
  because the tests passed for the wrong reason — the parity test
  compared evaluation against serving (the mutation moves both
  together) and the baseline test used a fixture where both branches
  returned tier1. Both were rebuilt on ABSOLUTE hand-computed
  assertions (filtered bounds [1,3] giving distances exactly 1.0,
  0.5, 0.0; a truth-switch-to-tier1 against an actual tier2 leg so
  the branches provably disagree) and then discriminated. The
  battery caught weak tests, which is what it is for.

Suites: calibration 51 OK, session-analytics discovery 389 OK (35
CI-gated skips), E1 calibration-additions + quality + redaction 95 OK.

## Verdict

Verdict: aligned
Confidence: high

The bundle covers exactly the five §12 conditions and the shadow kNN
bullet, nothing more; the single addition beyond §12's literal text —
corpus-bound staleness (decision 3) — exists so a gate can never pass
against evidence it was not computed from, which is the §12 intent
("evaluated against held-out tasks" of the actual corpus). Plan
status: draft, pending owner review.
