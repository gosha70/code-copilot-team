# Tasks: calibration gates + shadow kNN recommender (E3 of #109)

Each task lands only after the prior task's review round closes, with
its round recorded in the origin-alignment file. Contracts live in
plan.md (single normative source); tasks reference decisions, they do
not restate them.

## T1 — Schemas, corpus identity, configuration

- The three new schemas (plan decisions 2, 5, 6), validated by the
  in-repo validator subset (no unsupported keywords).
- `corpus_id` computation + stale detection (decision 3).
- Config keys through the standard layering (decision 8); no default
  values in Python source.
- Regressions: schema-level inverse tests for the closed vocabularies;
  corpus identity changes when a set is added/removed/invalidated;
  config layering pinned.

## T2 — Features, labels, and the kNN recommender

- Feature/label extraction (decision 4) and the deterministic kNN
  derivation with neighbor provenance and floor filtering
  (decision 5).
- Regressions: byte-identical output on identical corpus; tie-break
  determinism; `k_min` insufficiency; floor filtering removes
  below-floor candidates BEFORE ranking (mutation: filter after
  ranking must discriminate); neighbors resolve as addressable
  references against the served artifacts (the E2 followability
  precedent).

## T3 — Held-out evaluation and the gates

- Leave-one-task-out evaluation, the false-downgrade metric, durable
  atomic reports (decisions 6–7); the five gates computed from corpus
  + reports (decision 2).
- Regressions: leakage mutation discriminated; false-downgrade
  arithmetic vs a hand-computed fixture; truth-exclusion rule; each
  gate's pass/fail/insufficient_data tri-state pinned including
  missing-report and stale-corpus paths; G5's structural conjuncts.

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
