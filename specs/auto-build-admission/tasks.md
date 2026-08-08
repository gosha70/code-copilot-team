# Tasks: verification.yaml traceability + admission (#193, Increment B of #190)

Admission proves sufficiency, never creates it. After this increment an
admitted `unattended` run executes for the first time; everything not
admitted stays fail-closed. Targets **#193**; leaves umbrella **#190**
open. `SC` = success criterion in `spec.md`.

## Phase 1 — Artifact first: schema + generator + admission mode

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 1 | | `shared/schemas/verification.schema.json`: status draft/finalized; per-FR entries (statement, statement_sha, verifiers); kinds deterministic (test, metric?) / runtime_conformance (criterion). | `shared/schemas/` | SC-1/2 |
| 2 | | `scripts/lib/verification-common.sh`: FR extraction from `## Requirements`, canonical normalization, `sha256("FR-N: <text>")` — single implementation for generator AND admission. | `scripts/lib/` | SC-1 |
| 3 | | `scripts/generate-verification-draft.sh <feature-id>`: deterministic draft with computed hashes + rejected-by-admission placeholders; refuses to clobber finalized (`--force` drafts only). | `scripts/` | SC-1 |
| 4 | | `validate-spec.sh --unattended` (+ `--feature-id`): FR-4 checklist, all failures reported, DEFERRED (increment C) lines for floors/UI/migrations/secrets. | `scripts/validate-spec.sh` | SC-2 |
| 5 | | Tests: `tests/test-verification-spec.sh` — round-trip, reject matrix per check, sha drift on one FR, phantom/missing FR, placeholder, runtime_conformance inadmissible, phrasing lint, determinism; wire into sync-check CI. | `tests/`, `.github/workflows/` | SC-1/2/6 |

## Phase 2 — Admission live in the driver

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 6 | | Delete `CCT_AUTOBUILD_TEST_SEAM`; unattended preflight runs `validate-spec.sh --unattended`; failure = exit 1 config error (not admitted → no termination artifacts); success admits the run. | `scripts/auto-build-loop.sh` | SC-3 |
| 7 | | Honest finalize: ledger `.capability_downgrade` field; finalize/`automation-summary.md`/triage report the effective downgraded-unattended state, never "advisory". | `scripts/auto-build-loop.sh` | SC-5 |
| 8 | | Tests: admission-passing unattended fixture (finalized artifact, verifier = fixture test script) runs the previously-seamed paths; refusal fixtures per check; seam absence asserted; downgrade honesty; attended byte-identical. | `tests/test-auto-build-loop.sh` | SC-3/5 |

## Phase 3 — Out-of-band cost channel + docs

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 9 | | Runner: per-invocation `CCT_REVIEW_COST_FILE` (fresh, pre-deleted); read/validate (object, total_cost_usd ≥ 0) → measured; REMOVE the in-band final-line acceptance. | `scripts/review-round-runner.sh` | SC-4 |
| 10 | | Adapters: `ollama.sh` writes 0.0 (honest local-free); `openai-compatible.sh` writes only real USD (today: nothing — hook documented); cli opt-in documented. | `scripts/provider-adapters/` | SC-4 |
| 11 | | Flip the A-era regressions: final-line envelope now UNMETERED; cost-file path measured; negative/invalid file unmetered; attended v1 byte-identical. | `tests/test-auto-build-loop.sh` | SC-4 |
| 12 | [P] | Docs: SKILL admission + cost-channel sections (adapter copies synced), README/CHANGELOG, #190 umbrella comment for increment B. | skills, docs | SC-6 |

## Global definition of done

Admission bar per spec FR-4 with named failures + DEFERRED visibility ·
seam variable absent from the driver · admitted runs execute, refused
runs exit 1 with no artifacts · reviewer text can never measure cost ·
downgraded runs report honestly · attended profiles byte-identical ·
all suites green · per-phase review loop · targets **#193**, leaves
**#190** open.
