# Tasks: calibration gates + shadow kNN recommender (E3 of #109)

Each task lands only after the prior task's review round closes, with
its round recorded in the origin-alignment file. Contracts live in
plan.md (single normative source); tasks reference decisions, they do
not restate them.

## T1 — Schemas, identities, configuration, and the labeled E1 additions

- The five new schemas (plan decisions 2, 5, 6, 11), validated by the
  in-repo validator subset (no unsupported keywords).
- The decision-11 E1 additions: `task-descriptors.json` +
  `profile-policy.json` derived at publication, staged, scrubbed,
  manifest-bound, validated; pre-addition sets load as unlabeled.
- `corpus_id` + `policy_id` computation and stale detection
  (decision 3).
- Config keys through the standard layering, including
  `policy_source` (decision 8); no default values in Python source.
- Regressions: schema-level inverse tests for the closed vocabularies;
  the decision-11 binding set (missing/tampered/orphaned/pre-addition)
  in the E1 suite with existing E1 suites green; corpus identity
  changes when a set is added/removed/invalidated; policy identity
  changes for EACH policy dimension (k, metric, floor, policy-source
  digest); config layering pinned.

## T2 — Features, labels, and the kNN recommender

- Feature/label extraction (decision 4) and the deterministic kNN
  derivation with neighbor provenance and floor filtering
  (decision 5).
- Regressions: byte-identical output on identical corpus + policy;
  every decision-5 rule discriminated (encoding, missing-value
  refusal, fold-fitted normalization, weight formula, conservative
  tie to no_change, suggestion resolution incl. the
  current-policy-miss path); PRE-ROUTING feature ban (mutation: add a
  post-execution figure to the vector — must discriminate);
  current-policy filtering BEFORE ranking (mutation: filter after
  ranking); `k_min` insufficiency; neighbors resolve as addressable
  references against the served artifacts (the E2 followability
  precedent).

## T3 — Held-out evaluation and the gates

- Leave-one-task-out evaluation, the false-downgrade metric, durable
  atomic reports (decisions 6–7); the five gates computed from corpus
  + reports (decision 2).
- Normalization parity with serving: LOTO fits bounds on the SAME
  eligibility-filtered pool the recommender uses (carried from the T2
  review).
- Regressions: pool-leakage, full-corpus-normalization, AND
  filtered-vs-unfiltered bound-fitting mutations
  discriminated; false-downgrade arithmetic vs a hand-computed
  fixture covering BOTH decision-7 baseline branches
  (truth-switch-within-tier-1 predicted-tier-2 counts); tier
  resolution from the persisted profile policy; truth-exclusion rule;
  each gate's tri-state pinned including missing-report,
  stale-corpus, AND stale-policy paths; G2 fails on an unlabeled
  corpus; G5's three structural conjuncts.

## T4 — API + Studio surface

- Routes and payload builders (decision 10) under the E2 sanitization
  floor; Studio Calibration panel + labeled kNN section with openable
  neighbors.
- Browser verification against live fixtures at 1440/375: no-data,
  insufficient, gates-mixed, gates-all-pass, stale; sensitive-root
  absence swept over the new payloads; CI-gated HTTP tests.

## T5 — Docs, proofs, closure

- Docs (plan Files list); the authority-guard extension proven;
  routing shell suites unmodified at their pins; production-file diff
  guard empty vs master; full component sweeps with any host-baseline
  failures reproduced and classified at the merge base; origin
  refresh; PR body carries the single close keyword for #266 and
  explicitly leaves #109/#248/#254 open.
