---
spec_mode: full
feature_id: auto-build-admission
risk_category: integration
justification: |
  Increment B of umbrella #190: a new traceability artifact + schema, a
  new admission mode in validate-spec.sh, driver preflight rewiring that
  admits live unattended execution for the first time, an adapter-level
  cost channel replacing the in-band envelope, and finalize honesty
  changes. Security-adjacent (admission gate), schema work, >2 files —
  full mode.
status: draft
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/193
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/190
  origin_claim: |
    From umbrella #190, increment B verbatim: "traceability + admission.
    verification.yaml schema, draft generator, statement_sha binding,
    verifier-coverage enforcement, validate-spec.sh --unattended. Gate
    on this before any run lands." Plus #190 §3 ("Every requirement in
    spec.md MUST map to one or more verifiers before an unattended run
    is admitted... generated as a draft before admission, reviewed and
    finalized by the author, then validated at admission. Admission
    never authors it"; "spec.md is the only authoritative source of
    requirement text... admission recomputes every hash and fails on any
    mismatch") and §11 (the admission bar). Additionally the two
    increment-A preconditions recorded in
    specs/auto-build-unattended-core/spec.md: out-of-band cost channel
    before live unattended runs; honest finalize under gh capability
    downgrade.
---

# Plan: verification.yaml traceability + unattended admission (#193)

## Design

### D1 — Artifact + canonical normalizer
`shared/schemas/verification.schema.json` (draft-07) is the contract;
one shell function library (`scripts/lib/verification-common.sh`,
sourced by generator and validator) owns FR extraction, normalization
(continuation-join, whitespace-collapse, trim) and
`sha256("FR-N: <text>")` — a single implementation so the generator and
admission can never disagree. FR extraction anchors on the existing
`- FR-N:` / `- **FR-N — …**` bullet conventions in `## Requirements`
(the universal convention across specs/, per #190 §3).

### D2 — Generator
`scripts/generate-verification-draft.sh <feature-id>`: deterministic,
no model. Emits `status: draft`, per-FR entries with computed hashes and
`kind: deterministic, test: "TODO — map to an executable verifier"`
placeholders that admission rejects. Refuses to clobber `finalized`
(`--force` only regenerates drafts). YAML emitted via plain text
(consistent field order) so diffs are reviewable.

### D3 — Admission mode
`validate-spec.sh --unattended` (requires `--feature-id`): after the
existing structural checks, run the FR-4 checklist; collect ALL
failures; print `DEFERRED (increment C)` for the §11 items owned by C
(floors/baselines, DESIGN.md/UI, migrations, secrets). Parsing YAML in
bash: constrain the artifact to the flat two-level shape of D1 and parse
with awk/sed anchored on the schema (the schema file is the contract;
the script is the enforcement — same split as increment A's
automation.json validator). jq stays for automation.json.

### D4 — Driver wiring
Delete the seam block; in its place, for `profile: unattended` only:
`bash "$SCRIPT_DIR/validate-spec.sh" --unattended --feature-id
"$FEATURE_ID"` at the same preflight position (before any session,
ledger optional at that point). Failure → preflight error exit 1 (not
admitted → no termination artifacts). Tests build admission-passing
fixtures: a finalized verification.yaml whose deterministic verifier is
the fixture's own `./project-test.sh`.

### D5 — Cost channel
Runner: before each invocation, set `CCT_REVIEW_COST_FILE` to a fresh
path in its scratch dir (delete pre-invocation); after, read/validate
(object, `total_cost_usd` number ≥ 0) → measured, else unmetered. The
in-band final-line acceptance from increment A is removed. Adapters:
`ollama.sh` writes `{"total_cost_usd": 0.0}`; `openai-compatible.sh`
writes only if it can compute real USD (today: it cannot → writes
nothing; the hook point is there for priced deployments); documented
opt-in for `cli` commands. A-era regressions flip: genuine-final-line
envelope must now be UNMETERED; a cost file with the same content is
measured.

### D6 — Honest finalize
Preflight downgrade sets `CAPS_DOWNGRADED_CAUSE`; ledger gains
`.capability_downgrade` (string|null, skeleton + downgrade site);
finalize/`automation-summary.md`/triage report branch on it — the
"advisory" wording is reserved for the actual advisory profile.

## Deliverables

1. Schema + common lib + generator (+ tests).
2. `validate-spec.sh --unattended` (+ tests).
3. Driver admission wiring, seam removal, honest finalize (+ tests).
4. Runner/adapters cost channel, in-band removal (+ flipped tests).
5. Docs: SKILL admission section, README/CHANGELOG, #190 comment.

## Sequencing (phases; per-phase review loop as #191)

1. **Phase 1 — artifact first:** schema, common lib, generator,
   admission mode + tests (SC-1/SC-2). Nothing behavioral in the driver.
2. **Phase 2 — admission live:** seam removal, driver wiring, honest
   finalize + tests (SC-3/SC-5).
3. **Phase 3 — cost channel + docs:** runner/adapters channel, in-band
   removal, flipped regressions, docs, umbrella comment (SC-4/SC-6).

## Test strategy

- Generator/admission unit suite (new `tests/test-verification-spec.sh`):
  round-trip, per-check reject matrix, sha drift, phantom/missing FR,
  placeholder, runtime_conformance rejection, phrasing lint, DEFERRED
  lines, determinism (two runs byte-identical).
- Driver suite: admission-passing unattended fixture runs (seam gone),
  refusal fixtures (exit 1, no artifacts), downgrade honesty assertions,
  attended byte-identical regressions.
- Runner suite additions in the driver tests: cost-file measured path,
  in-band text (mid-body AND final-line) unmetered, negative/invalid
  file unmetered.
- Full existing battery (driver, validator, supervisor, review-loop,
  sync, shared-structure).

## Leans recorded (proceeding per the established loop)

1. `runtime_conformance` mappings are inadmissible in B (evaluator is
   C) — the honest reading of "a verifier something depends on cannot be
   switched off".
2. Admission failure at preflight is exit 1 (config error), not exit 6:
   nothing was admitted, so nothing "terminated".
3. §11 items owned by C print as DEFERRED rather than silently passing.
4. Verifier execution at finalize ("landed requires every mapped
   verifier green") is C's verification orchestration; B admits, C
   verifies. test.command on the base ref IS run at admission (§11).
5. ollama measured-cost 0.0 is honest (local inference), not an
   estimate-suppression trick; recorded in the SKILL.
