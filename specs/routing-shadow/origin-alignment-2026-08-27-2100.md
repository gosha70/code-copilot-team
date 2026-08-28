# Origin Alignment Check — routing-shadow

Date: 2026-08-27 21:00 (record opened)
Trigger: rev-1 SDD bundle authored for increment E2 of #109 (#261),
immediately after E1 (#260) merged via PR #262 (97d372c) and the owner
directed continuation toward completing #109. E2 is the second half of
the owner's 2026-08-25 E1/E2 split.

## Origin sources read

- #261 issue body (owner-authored): scope ("Consume E1 artifacts
  through session analytics / studio", "shadow-mode recommendations
  only", "Compare actual routing against suggested routing", "Include
  evidence, confidence, and insufficient-data states", "No automatic
  policy changes and no kNN routing until #109's calibration gate is
  satisfied"); the dependency rule ("If E2 needs a measure E1 does
  not emit, that is an E1 change, not an E2 workaround"); the
  shadow-mode contract (every recommendation carries evidence,
  confidence with basis, and an insufficient-data state distinct from
  "no change recommended"); the acceptance list (renders E1 artifacts
  without re-deriving any metric; actual and suggested shown together
  with explicit divergence; addressable evidence and stated
  confidence basis; insufficient data a distinct rendered state; no
  code path applies a recommendation and none is readable by the
  router at execution time; the §11 redaction constraint holds for
  the analytics surface); the non-goals.
- #109 §Delivery Plan Increment E — the two deliverables E1 left:
  "Studio/session-analytics surface" and "Shadow-mode routing
  recommendations" ("Optional similarity/kNN policy only after
  calibration" stays out per #261).
- #109 §11 Telemetry and explainability — the redaction constraint
  quoted verbatim in #261's acceptance.
- #109 Acceptance §Evaluation and observability — the one remaining
  unchecked box: "Learned routing remains shadow-only until explicit
  calibration gates are met."
- specs/routing-eval/ — E1's frozen evidence contract:
  routing-run.schema.json, outcome-matrix.schema.json, the
  build_report output shape, the write-time redaction gate, and the
  five T7 audit rounds that hardened selector authority.
- The session-analytics arc: scripts/session_analytics/ (pipeline +
  FastAPI API), studio/ (Next.js UI), and
  specs/session-analytics-benchmark-ui/ — the direct precedent for a
  read-only artifact-consuming Studio surface (typed fetcher, empty
  state, no backend re-derivation).

## Working claim

E2 supplies the consumption layer for E1's evidence: discovery and
fail-closed validation of E1 evidence sets, a Studio surface that
renders E1's figures verbatim, and shadow-mode recommendations —
per-task claims derived only from E1's own arms (actual = the
router's recorded selections; suggested = the always_best arm's
choice with the oracle named as ceiling), each carrying addressable
evidence references, a stated confidence basis, and a closed
three-state outcome where insufficient data can never collapse into
"no change recommended". No execution authority: nothing the router
reads changes, enforced by the inherited diff guard plus a
no-production-reference guard.

## Mismatches / deviations from the origin sketch

1. **The report becomes a persisted E1 artifact.** #261 says E2
   "reads … the comparison report", but E1 computes build_report
   without persisting it. Recomputing in the analytics process would
   re-run E1's authority chain (registry, validated config,
   selections) in a foreign context. Resolved per #261's OWN rule —
   "that is an E1 change, not an E2 workaround": plan decision 2 adds
   `write_report` to routing_eval (canonical, atomic,
   freshness-refusing, same discipline as write_run_records) as an
   explicitly labeled E1 contract addition, built and tested in T1 of
   this increment. Recorded for owner review at the plan gate.
2. **Recommendation vocabulary is an additive frame.** #261 names the
   three-part contract (evidence, confidence, insufficient-data) but
   not a record shape. Plan decisions 4–5 close it: a versioned
   recommendation.schema.json with a closed outcome vocabulary and a
   declared confidence-basis tuple. This frames #261's contract; it
   does not add measures, reweight anything E1 owns, or introduce any
   scoring of its own (suggested = E1's always_best selection,
   divergence = subtraction of E1's served figures).
3. **"Session analytics / studio" is the existing #63 surface.** E2
   extends the shipped pipeline/API/Studio rather than building a new
   surface — consistent with #109's file inventory naming `studio/`
   and with the benchmark-ui precedent.

## Plan review round 1 (owner) — six P1, two P2, rev-2 applied

All verified against the repository before applying; none accepted on
report alone.

1. **[P1] No production path creates the evidence set.** Verified:
   run_hybrid_scenario publishes only routing-runs.jsonl;
   build_matrix/build_report have only test callers. Resolved:
   decision 2 — `publish_evidence_set`, ONE E1 orchestration
   entrypoint (hybrid scenario + production matrix sweep + selections
   + report + publication of all three artifacts), T1.
2. **[P1] The report cannot support the recommendations.** Verified:
   build_report emits aggregate arm figures only — no schema_version,
   registry digest, source identity, or per-task provenance, and no
   report schema exists. Resolved: decision 3 — report contract v1
   with report.schema.json, full fingerprint, source-artifact
   bindings, per-arm selection provenance, and the per-task figure
   table (E1's own intermediate aggregation values, additive only).
3. **[P1] switch_profile must be positive evidence, not identity
   difference.** Verified: always_best is configured strength
   (tier/priority), not observed quality — a router can outperform it.
   Resolved: decision 5's dominance rule — a candidate arm must
   strictly beat the router's per-task quality at no greater cost (or
   tie quality at strictly lower cost); only executable arms are
   candidates (the oracle is a named ceiling, never suggested);
   router-outperforms-controls yields no_change_recommended and is a
   pinned regression.
4. **[P1] "Per task" was undefined across trials and chains.**
   Resolved: the unit is (evidence set, task); trials aggregate via
   E1's own per-task figures; `actual` is a closed per-trial
   structure (ordered profile chain, delegated?, reconciled?) that is
   display and evidence, never the trigger.
5. **[P1] Co-location does not bind artifacts into a set.** Resolved:
   the report carries sha256 source bindings computed from the same
   bytes written; the loader verifies hashes (hash and parse the same
   bytes) and cross-artifact fingerprint agreement before deriving
   anything; any failure is set-level invalid_evidence.
6. **[P1] Artifact paths violate the absolute-path prohibition.**
   Resolved: decision 6 — evidence references are {opaque
   evidence_set_id, artifact enum, locator}; absolute paths and `..`
   rejected at validation, containment and regular-file checks at
   resolution; the API speaks set ids, never filesystem paths.
7. **[P2] invalid vs insufficient conflated; confidence had no
   statement.** Resolved: invalid_evidence is SET-level and produces
   no records; insufficient_data derives only from valid sets and
   carries its references; confidence is a closed grade
   (high|moderate|low, declared deterministic rule over trials and
   mask completeness) plus its basis.
8. **[P2] "Byte-equal" is not implementable across JSON round-trips.**
   Resolved: decision 9 — the figure-provenance gate: exact source
   pointers, one canonical parse, semantic float64 equality, and
   recomputed declared subtractions for deltas.

## Plan review round 2 (owner) — four P1, three P2, rev-3 applied

1. **[P1] The fixed-profile executor did not exist.** Verified:
   SupervisorRunner.run_task invokes the router and harvests
   cct_router/profile_id-null only; build_matrix executes only
   eligible tuples. Resolved: decision 2 defines `run_profile_cell`
   (per-cell clean adapter-lifecycle context, injected-event parity,
   pinned-profile launch env with exact executed identity,
   driver-owned verification, profile_sweep harvest → Cell) and
   corrects the sweep wording to ELIGIBLE tuples executed /
   ineligible materialized per build_matrix's contract.
2. **[P1] Per-file atomicity is not set atomicity.** Resolved:
   staging directory, in-staging validation (the E2 loader's own
   checks), one atomic directory rename; fault-injection regressions
   after each step prove no discoverable partial set and rerun
   success.
3. **[P1] Identity collisions + impossible fingerprint comparison.**
   Verified: runs records carry four shared components by E1 design.
   Resolved: the set id is a CONTENT digest (full fingerprint + both
   source hashes); binding checks are pairwise — report↔matrix on
   five components, runs↔report/matrix on the shared four, plus the
   source-hash byte bindings.
4. **[P1] The confidence grade could assert high on contradictory
   evidence.** Resolved: report v1 emits per-trial values (E1's own
   cell-level intermediates, additively); grade rule v2 incorporates
   TRIAL AGREEMENT (switch: fraction of trials the suggested arm ties
   or beats the router; no-change: fraction where no candidate
   strictly exceeds) with declared thresholds (high: ≥5 trials, full
   mask, ≥0.8; moderate: ≥2, full mask, ≥0.6; else low). The
   single-outlier aggregate win grading low is the pinned regression.
5. **[P2] Comparison tolerances.** Resolved: E1's 1e-9 tolerance
   declared once and used for all Q and cost comparisons; equal =
   within tolerance, strictly greater = beyond it.
6. **[P2] Invalid-evidence diagnostics could leak paths.** Resolved:
   closed sanitized failure vocabulary (missing_artifact,
   unreadable_artifact, schema_invalid, hash_mismatch,
   fingerprint_mismatch, path_escape) with artifact enums and
   path-stripped details; sensitive-root regression across all
   failure modes.
7. **[P2] Settings and UI verification incomplete.** Resolved: the
   file map now covers AnalyticsConfig (field, defaults, layering
   tests) and /api/settings end to end; T4 adds browser-rendered
   assertions and screenshots (valid, invalid, empty, all three
   outcomes; desktop and mobile widths) through the UI-harness /
   visual-review loop, beyond `npm run build`.

## Plan review round 3 (owner) — four P1, two P2, rev-4 applied

1. **[P1] Router records did not reduce to one (task, trial)
   figure.** Verified: a delegated task yields provisional +
   reconciliation records and router_cells_from_records converts
   every record to a cell — double-weighting. Resolved: decision 3's
   NORMATIVE LIFECYCLE FOLD (a labeled E1 correction): one folded
   figure per (task, trial) — reconciled outcome scores, provisional
   never separately; cost is the declared sum across legs under
   provenance homogeneity; combined routing chain; exact coverage
   with duplicate/missing refusal; the delegated-task one-cell-not-two
   regression pinned.
2. **[P1] The content identity did not bind the report.** Resolved:
   an external `manifest.json` (own schema, written last in staging)
   hashes ALL THREE canonical artifact byte streams plus an
   evidence_files map for every referenced evidence file; the set id
   is the manifest's canonical-bytes sha256; serving an evidence file
   verifies its manifest hash. A schema-valid report edit now changes
   the identity — pinned regression.
3. **[P1] Fixed-profile launching lacked an authoritative
   mechanism.** Verified: profile→environment translation lives in
   cooldown-supervisor.sh post-selection. Resolved: the bridge is the
   UNMODIFIED production supervisor under a DERIVED single-profile
   registry (profile entry copied byte-for-byte; two profiles —
   builder + declared Tier-1 reconciler — for delegate-class cells,
   matching the build/bounded-build eligibility split); parity pinned
   by test (launch-env wiring vs production; all SEVEN executed
   identity fields vs the matrix fingerprint entry); the fingerprint
   keeps the declared full registry's digest with the derived entry
   verified against it.
4. **[P1] Agreement checked half the claim.** Resolved: agreement
   uses the SAME tolerance-aware two-axis dominance predicate as the
   recommendation, per trial, for both outcomes; an unpriced
   per-trial cost cannot evaluate the predicate — grade capped at
   `low` with the trial named. Quality-only-agreement is a declared
   discriminating mutation.
5. **[P2] Set-atomic semantics closed.** Hidden same-filesystem
   staging excluded from discovery; manifest last; idempotent no-op
   on byte-identical duplicate; refusal on differing content at the
   same id; owner-checked stale-staging cleanup.
6. **[P2] Tolerance attribution corrected.** E2 declares its OWN
   absolute 1e-9 rule; E1's actual behaviors (cost_reader isclose
   rel_tol=1e-9/abs_tol=1e-12; oracle exact-float sort) are recorded
   accurately and not claimed as precedent; boundary tests at the
   tolerance edge.

## Plan review round 4 (owner, on PR #263 @ bd4167d) — four P1, one P2, rev-5 applied

1. **[P1] A two-profile derived registry could not guarantee the
   pinned builder builds.** Verified: roles are not mutually
   exclusive, so a reconciler also holding bounded-build could win
   the builder selection — mis-attributing the cell or making it
   unexecutable. Resolved: STAGE-SPECIFIC derived registries (builder
   invocation: pinned profile only; reconciliation invocation:
   declared reconciler only), entries byte-for-byte from the full
   registry, seven-field identity parity asserted independently per
   lifecycle leg; the reconciler-with-bounded-build counterexample is
   pinned.
2. **[P1] The fold fixed cardinality, not metric semantics.**
   Resolved: a per-component fold contract — final leg for verifier
   outcome and the state regressions; UNION for scope violation and
   intervention; repeated repair over the CONCATENATED signature
   stream (cross-leg same-signature IS a repeat; per-leg-reduce-then-
   OR is a declared discriminating mutation); cost and elapsed summed
   under provenance homogeneity; ordered chain concatenation — with
   the SAME fold governing delegated profile_sweep cells so router
   and controls compare identical units. The clean-reconciliation-
   laundering discriminator is pinned.
3. **[P1] The manifest fingerprint was unbound.** Resolved: binding
   validation now requires manifest.fingerprint == report == matrix
   (full five) and manifest shared-four == every runs record;
   manifest-fingerprint-only tampering over genuine bytes returns
   fingerprint_mismatch (pinned mutation); the served set id is
   always recomputed as sha256(canonical manifest bytes) — directory
   names untrusted. The stale contract-table identity row was
   corrected (source: manifest.json).
4. **[P1] /api/settings would have leaked evidence-root paths.**
   Verified against the current API precedent (settings serves
   kuzu_path and sources raw). Resolved: evidence roots are
   server-side configuration only; /api/settings serves a sanitized
   shape ({configured, root_count} or opaque labels); the
   sensitive-root regression covers settings, evidence,
   recommendation, and error payloads.
5. **[P2] "Additive only" contradicted the labeled correction.**
   Resolved: the constraint now states E1 metric definitions,
   weights, selectors, and control semantics remain unchanged with
   ONE explicitly labeled correction (the lifecycle reduction), and
   "E1 suites pass unmodified" became "existing E1 behavior remains
   green, with targeted E1 regressions extended for the corrected
   lifecycle reduction".

The owner explicitly did not reopen the recommendation rule,
confidence thresholds, manifest architecture, or set-atomic
publication model.

## T1 build (2026-08-28) — the E1 evidence-set orchestration

Built per decisions 2-4 with the owner's three load-bearing
discriminators pinned. Live proof: publish_evidence_set drives the
one-trial arc fixture end to end — hybrid scenario, 15-cell matrix (9
executed through stage-specific one-profile derived registries, 6
ineligible), selections, report v1, manifest — validates in staging,
publishes atomically, is idempotent on byte-identical republication,
and refuses manifest-fingerprint-only tampering
(fingerprint_mismatch) and report edits (hash_mismatch) with
sanitized diagnostics. Fault injection at the matrix/report/validate
steps leaves no discoverable partial set and the retry succeeds. The
lifecycle fold's per-component contract is regression-locked
(laundering and cross-leg-repeat mutations discriminate); the
bounded-build reconciler steal is pinned live.

THREE implementation corrections surfaced by building the production
path, each grounded in production code and labeled:

1. **Eligibility class semantics are BUILT INTO rt_select, not read
   from registry tables.** The plan said tier membership in the
   class's declared tier_order; in production, rt_select's closed
   vocabulary hardcodes tier1_only = tier1-only and tier2_preferred =
   tier2-then-tier1 (routing-select.sh:142-208), and the registry's
   [route_classes.*] tables govern task-metadata validation, not
   selection. A table-based predicate wrongly ruled every profile
   ineligible under a registry that declares no such table (the live
   arc registry). The derived predicate now mirrors the selector's
   built-ins; the role half is unchanged.
2. **Measured cost IS harvestable — the "transcripts are transient"
   premise was false.** The supervisor durably copies every attempt's
   child output to RT_DIR/transcript-N.log (cooldown-supervisor.sh
   :1297/:1632/:2004) and result-N.json references it. Harvest now
   snapshots transcripts per invocation and sums
   cost_reader.measured_cost over the invocation's new transcripts —
   provenance measured; any transcript without a backend-reported
   value makes the invocation unavailable, never a partial sum. This
   is what makes a measured-basis evidence set publishable at all
   (always_cheapest refused the gate without it).
3. **routing-run.schema.json: insufficient_evidence became
   optional-but-nonempty.** With measured cost real, complete
   evidence is representable; the hollow-container refusal stands
   (present ⇒ minProperties 1), and absence now means complete. The
   schema rejection test was updated to the corrected contract.

OPEN QUESTION for the owner (round-5 language collision): decision 2
says sweep cells replay the task's injected events with router-arm
parity, but a provider-outage event against a PINNED single-profile
cell has no failover path — under default replay the cell dies and
the matrix loses coverage. T1 passes the events through as planned
(the live fixture encodes benign behavior via the explicit sweep
harness command); the likely right amendment is that router-arc
shaping events do not inject into fixed-profile cells, whose purpose
is profile capability, not outage response. Flagged, not decided.

## T1 build audit round 1 (owner, on 3a6acea) — three P1, two P2, applied

1. **[P1] Execution identity is now EXECUTION-PROVEN, all seven
   fields.** The T1 build asserted five declaration-derived fields and
   assumed effective==requested with the env-var NAME as endpoint.
   Fixed: per-leg observation from durable evidence — requested
   identity from started-N.json, tri-state effective model from the
   same attempt's result-N.json (null = unverified, production's own
   rule; a mismatch with the declaration refuses), and the sanitized
   RESOLVED endpoint from the actual launch environment
   (userinfo/query stripped, non-URLs digested; same env name +
   moved endpoint = different identity). Per-profile aggregation
   requires ONE compatible identity across all executed legs or
   nothing publishes; the fingerprint is built from observations
   (provisional fingerprint replaced post-sweep). Pinned: live
   fallback-verifies/preferred-unverified split (never
   requested-by-assumption), endpoint-changes-identity unit,
   corrupt-leg refusal units.
2. **[P1] Lifecycle exactness at the reporting boundary.**
   router_cells_from_records now verifies lifecycle SHAPE (ordinary =
   exactly one record; delegated = provisional then reconciliation,
   same seed, same packet id+digest; reconciliation-without-
   provisional and unreconciled-delegation refuse — the
   deleted-provisional laundering mutation dies) and, under the
   matrix build_report always passes, EXACT task x trial coverage
   with declared-seed pairing. Pinned: missing task, extra task,
   duplicate ordinary, wrong seed, missing provisional, mismatched
   packet digest.
3. **[P1 resolution of the flagged open question] Shaping events are
   ROUTER-ARM-ONLY — recorded as an E1 contract correction, not a
   silent code change.** The plan's "injected-event parity" wording
   is replaced: sweep cells run availability-neutral; the event
   stream stays in preset_digest so scenario changes still invalidate
   reuse. The downstream consequence is settled NOW as decision 5's
   AVAILABILITY GUARD: switch_profile is actionable only when the
   suggested profile appears admissible in the router's durable
   candidate evidence for the task; otherwise insufficient_data with
   the availability evidence referenced. T2 regressions pinned in
   tasks.md before T2 starts.
4. **[P2] Owner-checked stale-staging cleanup implemented**: a
   staging leftover is removed only when its recorded publisher pid
   is confirmed dead AND it exceeds the age window; live publishers
   and young directories are never touched (regression-locked). The
   publisher marker never ships with a published set.
5. **[P2] insufficient_evidence semantics honest**: ABSENT = no
   explicit insufficiency entries recorded (channels still express
   missing evidence via their own nulls); the schema header's
   "EVERY container required" claim now names the exception.

## T1 build audit round 2 (owner, on 2a1aa89) — two P1, one P2, applied

1. **[P1] Mixed verified/unverified evidence is never promoted.**
   Aggregation is now CONSERVATIVE: a non-null effective model is
   emitted only when EVERY executed observation verified the same
   model; one explicitly-unverified leg makes the profile null
   ([null, "m"] -> null, the flipped discriminator); conflicting
   non-null values still refuse. And the result read is FAIL-CLOSED:
   a missing or corrupt result-N.json after a successful invocation
   refuses (destroyed evidence is never converted into the unverified
   state) — production writes a durable result for every attempt,
   policy terminations included; only an explicit result without an
   effective model is the legitimate tri-state null.
2. **[P1] The endpoint identity covers the production surface and is
   collision-safe.** The authority is the persisted profile's
   endpoint_ref in production's own normalization (url:<literal> |
   urlenv:<name> | none — rc_profile_tuple), resolved exactly as
   rt_launch_env resolves it, so the shipped literal-base_url
   (DeepSeek-shaped) profile gets a REAL identity instead of null.
   The identity is redacted but FULL-VALUE-SENSITIVE: sanitized
   origin+path plus a sha256 of the complete resolved endpoint —
   same-host-different-query changes the identity (pinned) without
   exposing query or userinfo (pinned).
3. **[P2] Unprovable staging ownership is never deleted.** A missing
   or malformed publisher marker means the pid was never CONFIRMED
   dead, so the directory is skipped; old/no-marker and
   old/bad-marker cases regression-locked alongside the original
   three.

## T2 build (2026-08-28) — recommendation schema + the derivation module

T1 approved at c76024f; T2 built per decisions 4-6 with the owner's
named top discriminator pinned first:

- **recommendation.schema.json** (closed): the three-state outcome,
  suggested restricted to the executable arms, the oracle ceiling a
  separate named field, per-candidate divergence with the basis,
  confidence as grade + declared basis (trials, agreement,
  components_included, insufficiency refs, unevaluated trials), and
  evidence references as {set id, artifact enum, locator} with a
  CLOSED locator vocabulary (record/decision indices, arm+task keys,
  cell coordinates) — no path-shaped locator exists at all, a strict
  subset of the plan's allowance that removes the absolute-path risk
  class entirely.
- **session_analytics/routing_evidence.py**: discovery + loading
  through E1's OWN validate_evidence_set (one-way dependency;
  invalid sets surface as set-level invalid_evidence with the
  sanitized code, never skipped; LoadedEvidenceSet.path is
  server-side only); derivation as a deterministic projection —
  two-axis tolerance-aware dominance (never identity difference),
  THE AVAILABILITY GUARD (a numerically dominating candidate whose
  profile never appears admissible — verdict selected/eligible — in
  the router's durable candidate evidence for the task yields
  insufficient_data with the availability evidence referenced),
  insufficiency non-collapse, per-trial two-axis agreement behind
  the confidence grade, unpriced trials named and grade-capped,
  byte-identical derivation, every record schema-validated before
  return.
- Pinned: dominating-but-unavailable -> insufficient_data (never an
  inactionable switch); router-outperforms-controls -> no_change;
  equal-quality-cheaper -> switch to always_cheapest; tolerance
  boundary never flips an outcome; missing candidate/router/task
  figures -> insufficient_data; the aggregate-dominates-but-per-trial-
  loses fixture grades low (agreement 1/3). Mutations discriminating:
  guard removed (2 failures), agreement reduced to quality-only
  (fails the 1/3 fixture).
- Integration: a REAL published set built through the T1 writers
  loads, derives schema-valid records bound to the set id; a
  tampered report surfaces as invalid_evidence/hash_mismatch with
  sanitized detail.

## Verdict

Verdict: aligned
Confidence: high

Scope is exactly #261, which is exactly what remains of #109's
increment E after E1. The single substantive extension — persisting
the report — is the path #261 itself prescribes for a missing E1
emission, and is labeled as such for the owner's plan review.
