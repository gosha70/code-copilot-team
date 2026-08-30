# Spec: calibration gates + shadow similarity/kNN recommender (E3 of #109)

Increment E3 (#266) — the last unshipped bullet of #109's Increment E:
"Optional similarity/kNN policy only after calibration." E3 builds the
calibration gates themselves — #109 §12's five conditions restated as
executable checks over durable artifacts — and a shadow-only similarity
(kNN) recommender evaluated against held-out tasks. Nothing E3 produces
carries execution authority; promotion of learned routing to any
authority is a future, owner-initiated increment that may only begin
once the gates hold.

Grounding (verified 2026-08-29): E1 (#260) publishes validated evidence
sets (routing-runs + outcome matrix + report + manifest, set-atomic,
write-time-redacted); E2 (#261) consumes them read-only through
`session_analytics.routing_evidence.load_evidence_sets` and derives
dominance-based shadow recommendations served via `/api/routing/*` and
the Studio Routing tab. E2's standing gates (authority guard, verbatim
figures, provenance resolver, sanitized payloads) are the fixed floor
E3 builds on.

## User Scenarios

- US1: As an operator, I open the Studio's Routing view and see a
  Calibration panel: each of the five §12 gates with its status
  (pass / fail / insufficient_data), the measured value, the declared
  threshold, and addressable evidence for the measurement — so I know
  exactly how far learned routing is from being eligible for promotion,
  and why.
- US2: As an operator, beside each dominance-based recommendation I see
  the kNN shadow recommendation for the same task, clearly labeled as a
  distinct source, with its neighbors (which evidence sets and tasks,
  at what distance, with what outcomes) openable as evidence — so I can
  judge whether similarity-based routing agrees with observed dominance.
- US3: As an operator, when the accumulated evidence is too thin, every
  data-dependent gate and the kNN recommender itself tell me
  insufficient_data — never a silent pass, never a fabricated
  recommendation.
- US4: As a maintainer, I can run the held-out evaluation and read a
  durable, schema'd report: the split definition, per-task predictions
  vs ground truth, the false-downgrade rate against its threshold — and
  the calibration gates consume exactly that report, bound to the exact
  evidence corpus it was computed from.
- US5: As the #109 owner, I can prove learned routing is still
  shadow-only: no production routing script references anything E3
  ships, and the routing shell suites pass unmodified at their pins.

## Requirements

- FR-E3-1: **The calibration-gate contract is executable and versioned**
  (plan decision 2). The five §12 conditions are computed from durable
  artifacts only; each gate reports pass / fail / insufficient_data
  with its measured value, its operator-declared threshold, and
  addressable evidence references; a gate whose inputs are missing or
  stale reports insufficient_data, never pass. The overall verdict is
  calibrated only when every gate passes.
- FR-E3-2: **Reports bind to the exact corpus AND the exact policy**
  (plan decision 3). Gate and evaluation reports carry both the corpus
  identity and the evaluation-policy identity (classifier parameters,
  feature version, normalization, floors, and the current
  security/role policy digest); serving compares both to the live
  corpus and configuration and flags any mismatch as stale — a stale
  report never renders as current and satisfies no gate.
- FR-E3-3: **The kNN recommender is shadow-only, deterministic,
  leakage-free, and provenance-carrying** (plan decisions 4–5).
  Features are PRE-ROUTING only — no post-execution figure (the
  label's ingredients) ever enters the query vector; candidates are
  filtered against the operator's CURRENT tier/security policy before
  ranking; the classifier rules (encoding, missing-value refusal,
  fold-fitted normalization, weighting, conservative ties, suggestion
  resolution) are normative so two conforming implementations cannot
  disagree; identical corpus + policy yield byte-identical
  recommendations; every recommendation names its neighbors (set id,
  task, distance, label) as addressable references and is rendered
  beside — never in place of — the E2 dominance recommendation.
- FR-E3-4: **Held-out evaluation is leakage-free and durable** (plan
  decision 6). Splits are leave-one-task-out with all trials of the
  held-out task excluded from the neighbor pool and normalization
  fitted per training fold; the false-downgrade rate is computed
  exactly as plan decision 7 defines — against the truth's suggested
  tier when truth recommends a switch, against the router's actual
  tier when truth recommends no change; results persist as schema'd
  reports in the analytics-owned output root, atomically, never
  inside E1 evidence roots.
- FR-E3-5: **Thresholds are operator configuration, not code**
  (plan decision 8). Gate thresholds and kNN parameters load through
  the session-analytics config layering (defaults file < user config <
  env); no threshold constant lives in source.
- FR-E3-6: **No execution authority** (plan decision 9). No production
  routing script, schema, or config key references any E3 module or
  artifact; the standing E2 authority-guard test extends to every new
  module; E3 writes only into the analytics-owned output root.
- FR-E3-7: **Sanitized serving** (inherited from E2). New payloads
  follow the E2 boundary: no configured roots or server-side paths
  serialized, opaque identities, closed failure codes, figures served
  verbatim with the E2 provenance disciplines where they are copies of
  artifact figures.

## Constraints

- If E3 needs a measure E1 does not emit, that is an E1 change, not an
  E3 workaround (the E2 rule carries over verbatim). Two such changes
  are DECLARED and labeled (plan decision 11): per-task pre-routing
  descriptors and the executed registry's per-profile policy
  declarations, both manifest-bound artifacts of the evidence set.
  Sets published before the addition are treated as unlabeled — never
  guessed at.
- No new npm dependencies in studio; no new Python service
  dependencies (pure stdlib derivation, like E2).
- No online learning, embeddings services, or external model calls.
- Routing shell suites and production routing files: untouched
  (empty diff vs master; suites at their exact pins).

## Non-Goals

- Promoting learned routing to advisory or execution authority —
  explicitly a future increment, owner-initiated, gated on this
  increment's gates holding.
- Automatic actions of any kind when gates flip.
- Temporal splits (evidence sets carry no trusted ordering — directory
  names and mtimes are untrusted; leave-one-task-out is the split).
- New E1 METRICS: none. The only E1 changes are the two declared
  evidence additions of plan decision 11; metric definitions,
  selectors, and report semantics stay untouched.
