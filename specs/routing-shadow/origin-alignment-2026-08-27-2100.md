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

## T2 build audit round 1 (owner, on 8ef37e3) — three P1, two P2, applied

1. **[P1] Declared insufficiency states propagate.** Before dominance,
   the derivation now consults the router's and every executable
   candidate's `insufficient` maps AND the Pareto status: any
   declared insufficiency (e.g. cct_router sequence_dependent) or a
   withheld frontier yields insufficient_data with the named
   references, even when per-task figures are numeric. Pinned:
   router-arm insufficiency, candidate-arm insufficiency, withheld
   frontier; mutation (block skipped) fails all three.
2. **[P1] The dominating-arm tie-break is tolerance-aware.** The
   owner's exact counterexample pinned: qualities differing by 5e-10
   are EQUAL under the declared tolerance, so the lower-cost arm
   wins; harmless rounding can never change WHICH profile is
   recommended. Mutation (exact-float ordering restored) fails it.
3. **[P1] Malformed UTF-8 in routing-runs.jsonl stays inside the
   closed boundary.** The E1 loader decodes the runs artifact
   fail-closed into EvidenceSetInvalid(schema_invalid) like the other
   artifacts; the T2-level regression writes genuinely invalid bytes
   and asserts the set surfaces as invalid_evidence, never a raw
   exception (the future API-500 class).
4. **[P2] The full mask is an exact-set identity**, not a count: a
   right-length list with a duplicate and an omission never grades
   high (pinned both ways).
5. **[P2] `actual.reconciled` means the reconciliation SUCCEEDED**
   (outcome == "reconciled"), not that a record exists; a failed
   reconciliation renders false (pinned).

The owner explicitly did not reopen the recommendation architecture,
availability-neutral sweep decision, evidence-reference design,
dominance formula, or confidence thresholds.

## T3 build (2026-08-28) — the API layer and its three gates

T2 approved at 339de5b (the owner's non-blocking exact-assertion
tightening applied here). T3 built per decisions 7-10's API half:

- **Evidence roots, server-side only**: AnalyticsConfig gains
  `routing_evidence_roots` through the documented layering
  (defaults < user config < env `CCT_SA_ROUTING_EVIDENCE_ROOTS`,
  layering pinned); `/api/settings` serves ONLY the sanitized
  `{configured, root_count}` shape.
- **Endpoints** (thin wrappers over pure payload builders, unit-tested
  without fastapi per the suite's own convention; TestClient tests
  CI-gated): evidence index (valid summaries + set-level
  invalid_evidence entries, never skipped), set detail (the report
  VERBATIM), recommendations, and hash-verified evidence-file serving
  (manifest-membership + containment + hash before a byte leaves —
  unknown/escaping refs and tampered content refuse with closed
  codes; unverified artifact bytes are never served). Sets addressed
  by opaque id; unknown ids 404 with a closed detail.
- **The owner's named acceptance gate**: a deliberately sensitive
  evidence root (SENSITIVE-SECRET-DIR) proven absent across settings,
  index, detail, recommendations, served evidence files, AND
  invalid-evidence responses — at the payload layer locally and at
  the HTTP layer in the CI-gated tests.
- **The figure-provenance gate** (decision 9): every served figure
  semantically equals its artifact field from ONE canonical parse
  (arm quality/cost, per-task, per-trial rows), and every
  recommendation delta equals the recomputed declared subtraction of
  its two pointed-at fields.
- **The authority guard** (decision 7): no production routing script
  references this layer's module, schema, or config keys;
  consumption provably mutates nothing (evidence-set content digest
  identical before/after load+derive+serve); the consumer module's
  source contains no write calls.

## T3 build audit round 1 (owner, on a135289) — two P1, applied

1. **[P1] Hash verification proves integrity, not redaction — the
   scrub moved to the writer.** Referenced evidence files now pass
   through the SAME write-time scrub as every other published string
   AT PUBLICATION: `_publish` takes required `secret_values`
   (resolved by `publish_evidence_set` from the executed registry's
   own `credential_env` references), decodes each staged evidence
   file as UTF-8 (a non-decodable file refuses the set — an
   unscrubabble file never ships), writes the scrubbed bytes, and
   the manifest hashes the SCRUBBED bytes, so hash-verified serving
   can never faithfully deliver a secret or a home path. The owner's
   full-chain discriminator is pinned
   (TestEvidenceFileRedactionChain): registry declares
   `credential_env = "E2_BORING_TOKEN"`, the environment holds the
   deliberately boring `correct-horse-X7`, the raw verifier evidence
   carries that token plus the machine's own home-anchored worktree
   path; after publication the persisted evidence-file bytes and the
   API-served content contain neither, and the scrubbed forms
   (`[REDACTED]`, `~/…`) are asserted PRESENT so the test
   discriminates "scrub ran" from "leak never reached the file".
   Mutations: raw-copy (scrub disabled) fails the token assertion;
   raw-hash (manifest hashes source bytes) trips the in-staging
   `hash_mismatch` refusal. The sensitive path is the CURRENT user's
   home (decision 8's declared guarantee — the home prefix collapses
   so no username ships); a foreign `/Users/<other>` literal is
   outside the closed reviewed pattern set and was not smuggled in
   as scope.
2. **[P1] Decision 9 implemented as approved (owner's Option A) —
   payloads carry the pointers, one resolver validates before
   serving.** `recommendation.schema.json` gains closed source
   descriptors: `oracle_ceiling.sources` (RFC 6901 `figure_source`
   into the report per non-null figure, null source iff null figure)
   and per-arm `divergence[…].sources` (`delta_source`:
   `operation: subtract` + lhs/rhs figure sources), both required.
   The derivation emits them; `verify_recommendation_provenance` —
   THE resolver — runs inside `recommendations_payload` before
   anything is served: it resolves every pointer against the one
   canonical report parse, requires float64 equality for direct
   figures, and recomputes every declared subtraction requiring
   exact equality. No source, an unresolvable pointer, a non-numeric
   resolution, or a differing value refuses the whole payload.
   Pinned: independent re-resolution of every served source;
   missing-pointer, unresolvable-pointer, delta-vs-recomputation
   (1e-12 perturbation), wrong-operand (resolvable but wrong field),
   and gate-wired-at-serving regressions. Mutations (all
   discriminated): rhs pointed at the router arm; recomputation
   comparison removed; serving path severed from the resolver;
   builder emitting unsourced divergence (schema refuses).

Scoping note recorded for review: `confidence.basis.agreement` and
`trials` are derived statistics of the derivation itself, not copies
of artifact figures — their provenance is the basis block decision 5
defines (trials, components, unevaluated_trials, insufficiency
refs), and no direct-pointer source exists for them by construction.
Suites after the round: routing-evidence 41/41, E1 routing_eval
93/93, session-analytics discovery 331 (34 CI-gated skips), all OK.

## T3 build audit round 2 (owner, on 5c9fe4b) — three P1 + one P2, applied

All four findings were reproduced in-tree exactly as reported before
any fix, and re-run refused after.

1. **[P1] The manifest is now bound to ALL evidence references, both
   directions.** ONE canonical collector (`evidence_references`) reads
   BOTH reference-bearing channels the run schema permits —
   `verifiers[].evidence_ref` AND `repair_cycles[].evidence_ref` —
   and is the single authority: publication ships exactly that set,
   and validation requires the manifest's `evidence_files` keys to
   EQUAL it (new closed code `reference_mismatch`; an unbound record
   reference and an orphan hash-correct manifest entry both refuse).
   Publication also resolves each source under the evidence root
   before reading, so an already-relative reference over a symlink
   can never import an external file (the writer's absolute-path gate
   never sees a relative ref — this was a real hole).
   `_relativize_evidence` in the record writer now treats
   repair-cycle refs like verifier refs so the two channels behave
   identically. Pinned: the owner's emptied-map reproduction, the
   orphan-entry inverse, repair-ref publication+binding, and the
   symlink escape. Mutations (all discriminated): equality gate
   removed; repair channel dropped from the collector; containment
   check removed.
2. **[P1] "Exact source" is identity-bound.** Both `_check_direct`
   and `_check_delta` now require the served descriptor to EQUAL the
   canonical `_figure_source`/`_delta_source` for that record's task,
   arm, and field BEFORE resolving values — a resolvable-but-wrong
   pointer refuses even when the two artifact values collide. The
   owner's exact collision is pinned (always_best quality operand
   repointed at the oracle quality field with an equal 0.9 value,
   asserted equal in the fixture). The unresolvable-pointer
   regression was rebuilt to stay meaningful under identity binding:
   the descriptor is canonical but the artifact drifted underneath it
   (oracle task entry deleted from the loaded report). Mutation
   (identity check deleted) discriminated.
3. **[P1] Confidence claims are gated by recomputation.** Spec
   FR-E2-3 amended as the owner directed: figures that are copies of
   artifact fields carry identity-bound pointers; confidence
   statistics are statistics OF the derivation, carry no pointers,
   and are held to a recomputation gate — `_check_confidence`
   re-derives trials, agreement, the unevaluated set, and the grade
   from the canonical report and records and refuses on ANY
   disagreement. The owner's reproduction is pinned (one-trial record
   claiming grade high with agreement 0.0). Mutation (gate not
   called) discriminated.
4. **[P2] The persisted contract itself enforces the null/source
   pairing.** `oracle_ceiling` and each divergence entry gained four
   exclusive `oneOf` branches partitioning (figure × source) for both
   pairs — a numeric figure with a null source and a null figure with
   a non-null source are now schema-invalid, not merely
   runtime-refused (the validator subset has no `allOf`/`if`, so the
   branches conjoin with the existing `properties` keywords, which
   the validator applies conjunctively). Schema-level inverse tests
   pin all four wrong pairings for both ceilings and deltas.

Suites after the round: routing-evidence 44/44, E1
evidence_set+quality+redaction 97/97, session-analytics discovery
334 (34 CI-gated skips), all OK.

## T3 build audit round 3 (owner, on 75e1b5f) — one P1, applied

**[P1] The confidence gate no longer trusts ANY part of the served
basis.** Round 2's `_check_confidence` recomputed trials, agreement,
unevaluated trials, and the grade — but fed the payload's OWN
`insufficiency_refs` into the grade recomputation and never compared
`components_included` or `insufficiency_refs` at all. The owner's
reproduction (both fields fabricated while the four checked values
stay untouched; schema-valid; gate passed) was confirmed in-tree
pre-fix. The fix replaces piecewise recomputation with full
independent re-derivation: the gate calls `_derive_task` for the
record's task — which reconstructs `insufficiency_refs` from the
canonical report's declared insufficiency maps, the Pareto status,
per-task figure presence, the outcome path (selection provenance,
availability guard), and the availability evidence, and takes
`components_included` from the canonical report — and requires the
ENTIRE confidence block to equal the re-derivation. Pinned: the
owner's exact forged-basis shape (fabricated `components_included` +
`insufficiency_refs`, four previously-checked values asserted
unchanged). Mutation (comparison stripped of exactly those two
fields) discriminated with surgical precision: ONLY the new
regression fails, every other test passes. A first mutation attempt
was invalid (it introduced a NameError, failing six tests for the
wrong reason) and was discarded and redone honestly.

Suites after the round: routing-evidence 45/45, E1
evidence_set+quality+redaction 97/97, session-analytics discovery
335 (34 CI-gated skips), all OK.

## T4 build (2026-08-28) — Studio Routing view, browser-verified

T3 approved at 57a8303. T4 built per decision 10's conventions:

- **Typed fetchers** in `studio/lib/api.ts` mirroring the T3 payloads
  exactly (index entries as a `valid | invalid_evidence` union, the
  report v1 shape, the recommendation record with its decision-9
  source descriptors); three `api.routing*` fetchers. The Studio
  never re-derives a figure client-side.
- **Routing tab** in the `TABS` nav; index page (valid summaries +
  set-level invalid_evidence rows with sanitized code/label, never
  skipped; sanitized `{configured, root_count}` roots note;
  explanatory empty state pointing at `publish_evidence_set` and
  `CCT_SA_ROUTING_EVIDENCE_ROOTS`); detail page (fingerprint header,
  arms table with Q + component vector + cost/status + declared
  insufficiency, per-task figures, Pareto frontier or withholding
  reason, and per-task recommendation cards: three visually distinct
  outcome badges with explanatory copy — insufficient_data amber
  "cannot conclude", never rendered like no_change slate "concluded:
  keep" — actual per-trial chain with delegation/reconciliation
  markers, suggested profile, oracle ceiling labeled a non-runnable
  hindsight bound, explicit divergence deltas, confidence grade +
  basis including rendered insufficiency refs).
- **No new npm dependencies** in the studio; `npm run build` green.
  Prettier's hook churn on the three touched shared files was
  reverted and the edits re-applied surgically (additions-only diff).
- **Browser verification, not compiler-only**: real evidence sets
  published through the FULL E1 machinery (selector-computed
  controls) into a live root — one set per outcome (switch_profile
  via equal-quality-cheaper dominance with the profile admissible;
  no_change with the router on the frontier; insufficient_data via
  the availability guard with the alpha-in-cooldown candidate
  evidence) plus a byte-tampered invalid set — served by the real
  FastAPI app (scratchpad venv; fastapi is absent on the host) with
  the real Studio production build. A scratchpad Playwright runner
  (the ui-harness template's own mechanism; the template is not
  scaffolded into studio/ — no DESIGN.md exists there — so the
  harness's runner pattern was reproduced minimally) executed
  rendered assertions and full-page screenshots at 1440px and 375px
  for ALL states: empty, index (valid + invalid), and the three
  outcome details — 58 rendered assertions, all passing, including
  no-filesystem-path-leak checks on every page.
- **One shared-layout fix surfaced by the mobile pass** (labeled):
  the header nav overflowed the 375px viewport (white-on-white,
  pre-existing but worsened by the added tab) — the nav is now
  `overflow-x-auto` with a non-wrapping brand, the minimal fix the
  mobile acceptance itself demanded.
- Verification-honesty note: one screenshot pass captured an
  unstyled page — a stale `next-server` still held port 3000 while
  the build was rewritten under it (CSS 400). The stale process was
  killed, the studio rebuilt and restarted cleanly, and every
  screenshot re-taken with styles verified (css 200) before being
  trusted.

## T4 build audit round 1 (owner, on 9d07507) — three P1 + one P2, applied

1. **[P1] Null toolchain identity renders, never crashes.**
   `toolchain_digest` typed `string | null` in both the summary and
   report-fingerprint mirrors (matching the report/manifest schemas);
   `digest8` renders null as an em dash. Fixture note recorded for
   review: a LOADER-VALID set cannot carry a null toolchain today —
   the outcome-matrix schema requires a non-null string and the
   pairwise fingerprint-equality gate forces all three artifacts
   equal, and `build_report` itself refuses a null ("comparability is
   never silently assumed") — so the null lives only in the served
   report/record contracts. The browser fixture therefore exercises
   the schema-valid payload class by Playwright response interception
   on the detail request (real page code, controlled payload):
   "toolchain —" asserted rendered, no crash.
2. **[P1] Decision-bearing figures render VERBATIM.** One
   routing-specific formatter (`fig` — JS `String()`, the shortest
   round-trip representation) replaced every rounded rendering:
   quality, costs, per-task figures, Pareto, oracle ceiling,
   divergence deltas, and agreement. Boundary fixture published
   through the FULL E1 machinery: router cost `0.01 + 1e-8` vs a
   0.01 candidate — the 1e-8 delta exceeds the 1e-9 tolerance, IS
   the switch reason, and the page renders
   `9.999999999940612e-9` verbatim (asserted: scientific notation
   present, `0.0000` absent, outcome switch_profile).
3. **[P1] Recommendation evidence is addressable from the Studio.**
   Each card gains an "Evidence & sources" block: every
   `evidence_refs` entry rendered as artifact + typed locator
   (`RoutingEvidenceLocator` union added to the fetcher types; all
   three closed shapes labeled), plus the decision-9 source
   descriptors — oracle figure pointers and each delta's lhs − rhs
   operand pointers — verbatim. No recommendation reference addresses
   a served evidence file (the closed locator vocabulary has no file
   shape), so no evidence-file-endpoint link applies; the block says
   so explicitly rather than silently omitting links.
4. **[P2] The COMPLETE metric vector renders.** Arms-table columns =
   `components_included` in mask order, then every remaining served
   metric key (the sequence-dependent `tier2_accepted_unchanged`,
   `reconciliation_rework_ratio`, `rollbacks`) sorted — a stable
   canonical order over the full union.

Browser re-verification: the boundary set added to the live fixture
root; the runner now opens every `<details>` before text assertions
and asserts F3 (locators + pointers) and F4 (sequence-dependent
columns) on EVERY detail state — 10 page loads across 1440px/375px,
all assertions passing, `npm run build` green, diff additions-only on
the shared files.

## T4 build audit round 2 (owner, on fde3f1d) — one P1, applied

**[P1] Locators are now FOLLOWABLE, not just visible.** The owner's
first option implemented: a closed read-only artifact surface —
`serve_artifact` (`ARTIFACT_SURFACES = report / routing_runs /
outcome_matrix`) serving each VALIDATED artifact of a valid set
verbatim (content that already passed the full binding validation
and was scrubbed at write time), addressed only by opaque set id and
the closed artifact name; an unknown name refuses with the closed
`unknown_reference` code. Route:
`/api/routing/evidence/{set_id}/artifact/{artifact}`. In the Studio,
every evidence reference is a button: clicking fetches the artifact
through the typed `routingArtifact` fetcher and opens the EXACT
coordinate the locator names (`resolveLocator`: record[/decision]
into the served records, arm×task into the report, cell coordinates
into the matrix cells) as pretty-printed JSON in place; an
unresolvable locator renders an inline error, never silently
nothing. The explanatory sentence now states the follow behavior
(the evidence-file endpoint remains correctly unrelated, as the
owner confirmed).

Pinned server-side: `TestArtifactSurface` — each artifact serves
verbatim (equal to the loaded/validated content), unknown name
refuses closed; and the followability acceptance
`test_every_emitted_locator_resolves` — EVERY locator the derivation
emits resolves against the served artifact content (a derivation
emitting an unfollowable locator now fails a test, not a user).
`TestApiPayloadBoundary` sweeps the new surface for the sensitive
root; the CI-gated HTTP test covers the round trip and the closed
404. Browser: the runner clicks a `routing_runs` locator (asserts
the opened record's `"task_id"` renders) and a report locator
(asserts `"per_trial"` renders) on every detail state at both
widths — all passing. Suites: routing-evidence 47/47,
session-analytics discovery 338 OK (35 CI-gated skips),
`npm run build` green.

## T5 — docs, gates, closure (2026-08-29)

T4 approved at 3f52ad0. PR #263 was merged by the owner at that head
(merge commit 638d035) BEFORE the T5 closure commit existed — T5 was
deliberately held uncommitted until the full-sweep result was
classified, per the owner's sequencing instruction — so T5 lands as
this follow-up (branched from origin/master at 638d035), and #261
closes via the follow-up PR's single close keyword.

- **Docs**: README operator-docs pointer; CHANGELOG entry for #261
  (the shadow contract — evidence/confidence/insufficiency — and the
  calibration-gate stance); `scripts/session_analytics/README.md`
  § Routing evidence (full surface + contract + env config);
  `studio/README.md` Routing tab row + no-path note.
- **Decision-10/11 proof re-run**: production routing files, schemas,
  and shell suites show an EMPTY diff vs master on the whole branch;
  all six routing shell suites pass unmodified at their exact pins —
  config 167, failover 186, tasks 154, packet 99, delegation 171,
  recovery 375, 0 failed — so `tests/test-counts.env` is untouched.
  The standing authority-guard / verbatim / redaction-chain tests
  remain green in the analytics suite.
- **Full CI-exact sweeps**: session-analytics discovery 338 OK (35
  CI-gated skips). benchmark_runner full discovery: 1062 tests in
  ~29 min — 6 failures + 1 skip, ALL classified as the pre-existing
  host baseline, not regressions: the same six test IDs fail at
  merge base 97d372c (run in a pristine `git worktree` with the
  host's `benchmarks/.cache` symlinked in), with per-test failure
  signatures identical modulo only the checkout-root path prefix.
  The six: cli_skeleton ×2 (`rc 0 != EXIT_USAGE 2` — populated
  cache defeats the empty-cache USAGE assumption), polyglot
  golden ×2 (expected `leap.*` absent from the golden dir), polyglot
  verify ×2 (`/usr/local/opt/python@2/bin/python2.7: No module named
  pytest` — host interpreter resolution). The host baseline drifted
  from 4 (2026-08-27) to 6; the classification run is the proof.
  Verification-honesty note: the first sweep attempt died with a
  killed background task and the second silently failed to launch
  (macOS has no `setsid`) — both produced no result and were
  discarded; the recorded numbers come from the third, completed,
  detached run.
- **Gates**: `check-origin-alignment.sh routing-shadow` aligned/high;
  `validate-spec.sh --feature-id routing-shadow` 2 passed / 0 failed;
  `git diff --check` clean.
- **Close-keyword discipline**: every commit message on the branch
  audited clean; the follow-up PR body carries exactly ONE close
  keyword (for #261) and explicitly leaves #109, #248, and #254
  open.
- Out of scope, per the owner: `docs/developer-cookbook.md` stays
  untracked and lands on its own follow-up branch after this
  closure.

## T5 review round 1 (owner, on 7c4e459) — two P2 + one P3, applied

Documentation accuracy only — the owner confirmed branch structure,
closure discipline, gates, diff guard, and cookbook exclusion clean.

1. **[P2] The path-free claim was too broad.** Served evidence-file
   content can contain path-shaped text the scrub does not touch
   (only the current user's home prefix collapses; e.g.
   `/private/tmp/customer/project` survives), and evidence references
   are set-relative path shapes. The README/CHANGELOG/Studio claims
   now state the implemented boundary: configured roots and
   server-side set paths never serialized, opaque set identity,
   home-prefix collapse + credential scrub at write time — and
   explicitly that path-shaped text inside published evidence content
   is served as written.
2. **[P2] The provenance claim covered unsourced numbers.** "Every
   served number" narrowed to the decision-9 boundary: recommendation
   quality/cost figures and their deltas carry pointers; confidence
   statistics, record counts, and locator indices carry none —
   confidence is gated by whole-block recomputation instead.
3. **[P3] "`/api/settings` returns the dialect only" was false** —
   it returns several sanitized settings groups. Rephrased to "the
   DSN's dialect rather than the raw DSN (alongside other sanitized
   settings)".

## Verdict

Verdict: aligned
Confidence: high

Scope is exactly #261, which is exactly what remains of #109's
increment E after E1. The single substantive extension — persisting
the report — is the path #261 itself prescribes for a missing E1
emission, and is labeled as such for the owner's plan review.
