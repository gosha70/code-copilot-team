# T6.2 Design Read — verification gates (FR-016)

Status: **design read — paused for decisions before implementation.**
Scope: verification gates in the Pi runtime — build, unit/integration tests,
lint, type-check, security scan, dependency audit, visual review, docs
validation, generated-drift check; **required failures block phase completion.**

## Substrate audit (the "thin driver vs new" question — your prior, tested)

Two source reads. The T6.1 thin-driver pattern applies where a runnable script
exists. Reality is more mixed than "most already have substrates":

| Gate | Substrate | Verdict |
|---|---|---|
| **unit tests** | `verify-on-stop.sh` `detect_test_runner()` — npm/pnpm/yarn/bun, pytest, go, mvn, gradle, cargo (stack-agnostic) | **driver-able** |
| **drift check** | `generate.sh` + `sync-check.yml` diff + `tests/test-generate.sh` | **driver-able** (CCT artifacts) |
| **docs validation** | `validate-spec.sh` / `validate-pitch.sh` / `validate-capabilities.sh` / `validate-collaboration.sh` / `lint-wiki.sh` | **driver-able** (CCT artifacts) |
| **visual review** | `ui-harness` runner (`tsx src/runner.ts`, axe + Playwright) | **driver-able** (web UIs only) |
| **integration tests** | shares the unit substrate (no unit/integration split) | driver-able, no split |
| **build** | `verify-on-stop.sh` Docker build only; no generic language build | **partial** |
| **security scan** | `check-github-hardening.sh` (repo-config) + T5.3 protected-ops (runtime guard); **no code SAST** | **partial** |
| **lint** | only niche: `validate-workflows.sh` (CI YAML) + `lint-wiki.sh`; no generic code linter | **new** |
| **type-check** | none — the runtime strips types (`--experimental-strip-types` ≠ checking); no `tsc --noEmit`/`mypy` | **new** |
| **dependency audit** | **none found** — no `npm audit` / `pip-audit` / `dependency-review` anywhere | **new** |

**Count: 5 driver-able, 2 partial, 3 genuinely new.** Crucial caveat: the only
**stack-agnostic** substrate is `verify-on-stop.sh` (tests + docker). Everything
else that exists validates **CCT's own artifact types** (SDD docs, capability
registry, generated drift, CCT's own suites) — driver-able for CCT-shaped work,
but not a generic gate over an arbitrary target project.

## Orchestration surface (confirmed)

- **Config is dead + shapeless.** `verification.on_stop` (bool) is the ONLY
  verification key, set by `disciplined`, **read by no enforcement point** (like
  the T5.3 flags before they were wired). There is **no `verification.gates` /
  `verification.required` shape** and no floor entry — T6.2 must design the
  per-gate-required model.
- **Integration point = the T6.1 pattern, exactly.** Verification becomes a third
  conjunct: `canComplete = sddGate.pass && reviewGate.pass && verifyGate.pass` at
  `/cct:phase-complete` (index.ts), plus the `review→next` transition block.
- **No Stop event** (design-t51-events.md) ⇒ `verification.on_stop` cannot fire at
  session end; it fires at `/cct:phase-complete` — **same `degraded` posture** as
  `review.enforcement`. A `session_start` "unresolved failing verification"
  warning mirrors `midReviewWarning`.
- **No shared verify-runner exists.** Peer review has the neutral
  `review-round-runner.sh`; verification logic is trapped inside Claude's
  `verify-on-stop.sh` (report-only by default: `HOOK_STOP_BLOCK`, exit 2 to block).
- No `cct:verify` command; no `verification` capability; `/cct:status` doesn't even
  surface the review gate today.

## The honesty model (the spine of this design — mirror T5.1)

FR-016 lists ten gates; only 5 have real substrate, 2 partial, 3 none. **T6.2 must
NOT fake a gate it cannot run.** Mirror the T5.1 support model exactly: each gate
is `supported` (real substrate, runs), `degraded` (partial — e.g. build = Docker
only), or `unsupported` (no substrate — generic lint / type-check / dependency
audit), reported + audited, **never approximated**. A "PASS" must mean the gate
actually ran; an unrunnable gate reports `unsupported`, and a *required*
unsupported gate is a hard configuration error surfaced honestly (not a silent
pass). This is the same discipline as the T5.1 lifecycle-event support gate.

## Proposed design (pending approval)

- **Provider-neutral `verify-runner.sh`** (mirror `review-round-runner.sh`):
  wraps `verify-on-stop.sh`'s stack-agnostic detector (tests/docker) + the CCT
  validators (`validate-*.sh`, drift via `generate.sh`) + `lint-wiki.sh`, runs the
  configured gates, writes a structured `.cct/verify/result.json`
  (`{gate: {status: supported|degraded|unsupported, pass, detail}}`), exits
  0/1/2. Located via `CCT_VERIFY_RUNNER` env → sibling `scripts/` (mirror
  `resolveReviewRunner`). Absent → reported no-op.
- **`workflow/verify.ts`** (thin driver, mirror `review.ts`): `runVerify()`
  invokes the runner; `verifyGate(projectRoot, requiredGates, phase)` reads
  `result.json` and returns `{pass, reason}` — blocks phase-complete +
  review→next when a **required** gate is not a real PASS.
- **`/cct:verify`** command (mirror `/cct:review-submit`): runs the gates, reports
  per-gate status (supported/degraded/unsupported + pass/fail), audits
  (`origin: "verify-gate"`).
- **Config shape**: `verification.gates` = table of `<gate>: required(bool)` (or
  `verification.required` = list of gate names), plus `verification.on_stop`
  finally read. Floor: `array-union` on the required-gates list + `bool-or` on the
  on-flag (a trusted project may require MORE gates, never fewer) — new
  `SECURITY_FLOOR` entries. Lint: add the new keys to `KNOWN_KEYS`.
- **Capability**: add `verification.enforcement` = `degraded` with reason (Pi gates
  at phase-complete, no Stop event; some gate types unsupported for lack of
  substrate) — seed + `pi.yaml` + `catalog.yaml` + `claude-code.yaml`
  (drift-guarded, edit all).
- **Reporting**: `/cct:verify` + a `verify gate:` line in `/cct:phase-complete`
  and doctor.

## Decisions needed before implementation

- **A. Runner shape.** Extract a neutral `verify-runner.sh` (recommended, mirrors
  T6.1/D — single source, testable via stub) vs re-implement detection in TS?
- **B. Which gates ship "real" in T6.2.** Recommended: wire the **5 driver-able**
  (unit/integration-as-tests, drift, docs, visual, + build-docker) as `supported`;
  mark the **3 new** (generic lint, type-check, dependency-audit) and the SAST half
  of security as **`unsupported` with reason** (no substrate) — honest, not faked
  (T5.1 model). Do NOT build generic linters/SAST/audit here. Confirm — or do you
  want any of the three genuinely-new gates built now (each is a real, separate
  chunk of work)?
- **C. Config shape + floor.** Confirm `verification.gates` table (per-gate
  required) + monotonic floor (array-union required list, bool-or on-flag). Or a
  simpler `verification.required = [names]`?
- **D. Blocking default.** Claude defaults report-only. Recommended: a gate blocks
  phase-complete **only if listed required**; non-required run + report but don't
  block; a **required + unsupported** gate is a hard config error (surfaced, not a
  silent pass). Confirm the fail-closed-for-required posture.
- **E. Override boundary vs T6.3.** Recommended: T6.2 = gate + block + report only;
  the audited human **override / bypass** and `CCT_VERIFY_*` launcher env go to
  **T6.3** (mirroring how review's override is FR-000a). Confirm — or ship a
  minimal verify-bypass in T6.2 (as review shipped its own in T6.1)?
- **F. infra-verification-gate reconciliation.** `specs/infra-verification-gate/`
  *enhances* `verify-on-stop.sh` (infra + `bash -n`); T6.2's runner drives it —
  complementary. Confirm we treat it as substrate, not re-implement.

## Scope boundary

IN: `verify-runner.sh` + `workflow/verify.ts` + `/cct:verify` + phase-complete /
review→next blocking for required gates + config shape + floor + lint keys +
`verification.enforcement` capability + reporting + stub-runner tests (incl.
supported/degraded/unsupported + required-unsupported-is-a-config-error).

OUT: building generic code linters / SAST / dependency-audit tooling (no
substrate — reported unsupported); the human override + `CCT_VERIFY_*` launcher
env (**T6.3**); generalizing the CCT-artifact validators into arbitrary-project
gates.

## Decisions — CONFIRMED (with binding conditions)

- **A — neutral `verify-runner.sh`** (single source, stub-testable; TS stays a
  thin driver). Re-implementing detection in TS would be two-declarations-of-one-
  fact again.
- **B — ship the 5 driver-able + build-as-`degraded`; the 3 new report
  `unsupported` with reason; do NOT build them here.** DIRECTIVE: add a NAMED
  follow-up task to tasks.md so "unsupported" doesn't become "forever" — the
  first to build is **type-check** (a CCT-scoped `tsc --noEmit` over
  `adapters/pi/runtime`, NOT a generic-project gate). Rationale: the T1.5 undefined
  defect shipped precisely because `--experimental-strip-types` strips without
  checking; a scoped type-check has immediate defect-class coverage.
- **C — simpler shape: `verification.required = [gate-names]` (a LIST), not a
  per-gate table.** Deciding factor: the floor engine matches EXACT dotted paths
  with no wildcards, so a table needs ten hardcoded `verification.gates.<g>.required`
  floor entries, while the list needs exactly ONE `array-union` entry on the proven
  combinator. Keep `bool-or` on `verification.on_stop`. Per-gate options (timeouts
  etc.) are speculative — defer until a gate needs them, migrate via the v2→v3
  config chain.
- **D — required-means-blocking; required + `unsupported` is a HARD CONFIG ERROR,
  never a silent pass.** (The most important invariant.)
- **E — override/bypass + `CCT_VERIFY_*` launcher env → T6.3.** Safe to defer
  (unlike review's in-T6.1 bypass): a failing required verify gate already has an
  audited escape hatch — user-controlled layers (CLI/env/project-local) relax the
  required list through the floor's `relaxed-by-override` path, which is recorded.
  No deadlock, so no bespoke bypass needed in T6.2.
- **F — `specs/infra-verification-gate/` is substrate** (it enhances
  `verify-on-stop.sh`); drive it, do not re-implement.

### BINDING CONDITION — the absent-runner fail-open hole (must fix in design)

The proposed "runner absent → reported no-op" is WRONG as stated — it fails open.
Corrected contract:
- **runner absent AND the required list is non-empty ⇒ the gate FAILS** (fail-closed,
  config-error class). Otherwise deleting the runner silently passes every required
  gate.
- **runner absent AND nothing required ⇒ no-op is fine.**
Stub tests MUST cover BOTH cases, plus **required + unsupported ⇒ hard error**.
That trio is the leak-shaped test for this feature.
