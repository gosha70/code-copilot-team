# Spec: verification.yaml traceability + unattended admission (#193, Increment B of #190)

Turns "unattended verification" from an LLM opinion into an evidence
graph, and replaces increment A's fail-closed test seam with real
admission control. After this increment an `unattended` run that passes
admission executes for the first time.

## User Scenarios

- **US1 — Author maps requirements to verifiers.** After writing
  `spec.md`, the author runs the draft generator, gets a
  `verification.yaml` skeleton with one entry per `FR-N`, fills in real
  verifiers, and marks it finalized. They never hand-compute hashes.
- **US2 — Admission proves sufficiency, never creates it.** An
  `unattended` run refuses to start unless the finalized artifact passes
  the machine-checkable bar: full coverage, executable verifiers, hashes
  matching `spec.md`. The refusal names every failing check. Admission
  never edits the artifact.
- **US3 — Requirement drift is caught.** Editing an `FR-N` in `spec.md`
  after finalization invalidates that entry's `statement_sha`; the next
  admission fails on the mismatch until the artifact is re-finalized.
- **US4 — The meter cannot be written by the model.** Review-cost
  measurement moves to a file channel the reviewer's text cannot reach;
  in-band cost envelopes are no longer accepted at all.
- **US5 — Verdicts are honest under degradation.** A capability-
  downgraded unattended run reports itself as downgraded in the final
  summary and ledger — never as "advisory".

## Requirements

- **FR-1 — `verification.yaml` schema.** `specs/<feature>/verification.yaml`:
  a top-level `status: draft|finalized` plus one entry per `FR-N` with
  `statement` (generated display text, never authoritative),
  `statement_sha` (`sha256:<hex>` binding to spec.md), and `verifiers:`
  (≥1). Verifier kinds: `deterministic` (requires `test:` resolving to
  an executable target and optional `metric:`) and `runtime_conformance`
  (requires a concrete `criterion:`; its evaluator is increment C).
  A JSON-Schema contract file mirrors the rules (repo convention).
- **FR-2 — Statement normalization + hashing.** The authoritative text
  of `FR-N` is the content of its `- **FR-N — …**` / `- FR-N:` bullet in
  `spec.md`'s `## Requirements` section, continuation lines joined,
  whitespace collapsed, trimmed. `statement_sha` = sha256 over
  `FR-N: <normalized text>`. One canonical implementation, used by both
  the generator and admission — never two parallel normalizers.
- **FR-3 — Draft generator.** `scripts/generate-verification-draft.sh
  <feature-id>` emits `status: draft` with every `FR-N`, computed
  hashes, and placeholder verifiers that admission cannot accept.
  Refuses to overwrite a finalized artifact (`--force` for a draft).
  Generation is deterministic (no network, no model).
- **FR-4 — Admission bar: `validate-spec.sh --unattended`.** New mode
  (composes with `--feature-id`); every check independent, all failures
  reported, exit non-zero on any:
  1. `verification.yaml` exists and `status: finalized` (a raw draft is
     inadmissible).
  2. Coverage: every `FR-N` in spec.md has an entry with ≥1 verifier;
     entries for nonexistent FRs fail.
  3. Every `statement_sha` recomputes clean against spec.md (the only
     authoritative source of requirement text).
  4. Every `deterministic` verifier resolves to something executable
     (file exists / command resolves); placeholders fail.
  5. Any FR mapped to `runtime_conformance` fails admission in this
     increment — the evaluator ships in C and a verifier something
     depends on cannot be unavailable (honest fail-closed, #190 §3).
  6. Unverifiable phrasing lint: statements matching "user confirms",
     "looks good", "verify manually" (case-insensitive) fail unless
     carried by a `runtime_conformance` verifier (which then fails per
     check 5 — in B such specs are simply not admissible).
  7. `automation.json` passes `validate-automation-config.sh`, profile
     is `unattended`, caps explicit (delegated to the A validator).
  8. `test.command` from automation.json exists and passes on the
     CURRENT base ref (admission runs it once).
  9. `plan.md` `status: approved` and origin gate exit ≤1 (existing
     checks, kept).
  The §11 items owned by later increments (coverage floors/baselines,
  DESIGN.md/harness for UI scope, migration allowlist, secrets
  enumeration) are NOT silently passed: `--unattended` prints them as
  `DEFERRED (increment C)` lines so the operator sees the bar's known
  extent.
- **FR-5 — Real admission replaces the seam.** The driver's
  `CCT_AUTOBUILD_TEST_SEAM="pre-admission"` block is DELETED. For
  `profile: unattended`, preflight runs `validate-spec.sh --unattended
  --feature-id <id>`; failure is a preflight config error (exit 1 — the
  run was never admitted, so no termination artifacts); success admits
  the run, which then executes unattended (first increment where this
  happens). Attended profiles never invoke admission.
- **FR-6 — Out-of-band cost channel (A-precondition 1).** The runner
  exports a per-invocation `CCT_REVIEW_COST_FILE` (fresh path in the
  runner's scratch, removed before invocation); provider adapters —
  never the model's text — write `{"total_cost_usd": <n>}` there.
  `ollama.sh` writes `0.0` (local inference: measured-free is true);
  `openai-compatible.sh` writes only when it can derive a real USD cost
  (absent a price source it writes nothing → unmetered → estimate);
  `cli` provider commands may opt in via the documented env var. The
  runner reads cost ONLY from this file (non-negative number, else
  unmetered); the increment-A in-band final-line envelope acceptance is
  REMOVED. The A regression fixtures flip to prove in-band text can
  never measure.
- **FR-7 — Honest finalize under capability downgrade
  (A-precondition 2).** The gh downgrade records
  `capability_downgrade` in the ledger (field, not just journal);
  finalize and `automation-summary.md` report the EFFECTIVE state
  ("unattended (capabilities downgraded: <cause>) — nothing was
  pushed"), never "advisory", and the triage report carries it too.
- **FR-8 — Byte-identical attended surface.** No attended profile
  invokes admission, the generator, or the cost-file channel
  differently than today; existing suites stay green unchanged except
  where A's in-band-envelope tests are deliberately flipped by FR-6.

## Constraints / What NOT to Build (→ later increments of #190)

- No coverage floors, baselines, `skip_is_failure`, bounded-progress
  rules, per-phase contracts, or the runtime conformance evaluator (C).
  `landed requires every mapped verifier green` (§3 last rule) is C's
  verification orchestration — B admits, C verifies.
- No adjudication, builder/backend swap, run surface, presets (D); no
  parallel slices (E).
- No model-driven generation in the draft generator — deterministic
  text processing only.
- `origin_gate` terminate-only, security floors, deny rules: untouched.
- No new provider failover; no price tables beyond what an adapter can
  already derive (calibration is #190 §12 / increment D).

## Key Entities

- `specs/<feature>/verification.yaml` — status, FR entries,
  `statement_sha`, verifiers (`deterministic` | `runtime_conformance`).
- `shared/schemas/verification.schema.json` — the contract file.
- `scripts/generate-verification-draft.sh` — deterministic generator.
- `scripts/validate-spec.sh --unattended` — the admission bar.
- `CCT_REVIEW_COST_FILE` — per-invocation out-of-band cost channel.
- Ledger field `capability_downgrade` — effective-state honesty.

## Success Criteria

- **SC-1** Generator → finalize → admission round-trips on a real spec;
  editing one FR afterward fails admission on exactly that entry's sha.
- **SC-2** Admission rejects: draft status, missing FR entry, phantom FR
  entry, placeholder verifier, unresolvable test target,
  `runtime_conformance` mapping, unverifiable phrasing, failing
  `test.command` — each with a named check; DEFERRED lines printed.
- **SC-3** An unattended run with a finalized, passing artifact is
  admitted and executes (no seam); one failing any check refuses at
  preflight with exit 1 and no termination artifacts; the seam variable
  is gone from the driver.
- **SC-4** A reviewer whose TEXT contains or ends with any cost
  envelope is unmetered (estimate debits); a cost written via
  `CCT_REVIEW_COST_FILE` is measured; negative/invalid file content is
  unmetered. Attended v1 runs byte-identical.
- **SC-5** A gh-downgraded unattended run's summary/ledger/triage all
  say downgraded-unattended, never "advisory"; attended summaries
  unchanged.
- **SC-6** All suites green; new tests cover every SC.
