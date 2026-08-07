---
spec_mode: full
feature_id: auto-build-unattended-core
risk_category: integration
justification: |
  Increment A of umbrella #190: terminal-outcome vocabulary + disposition
  dispatch in the autonomous build driver, a new config schema/validator,
  and closing the cost-metering hole (review rounds are unmetered today).
  Touches the driver, the review runner, the cooldown supervisor, and the
  SDD template; full mode per schema+integration+>2 files. Deliberately
  runs nothing unattended (fail-closed preflight until increment B lands);
  attended profiles must stay byte-identical.
status: draft
date: 2026-08-07
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/191
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/190
  origin_claim: |
    From umbrella #190 (unattended autonomy profile), increment A: "policy
    core + metering. Terminal-outcome vocabulary, unattended profile,
    disposition dispatch (terminate-only), termination artifacts (§9),
    automation-config schema + validator, origin_gate hard rule, full cost
    accounting incl. conservative estimates (§2). Nothing runs unattended
    before B." Bound, decide, and record — never block: every breaker
    resolves to a journaled policy decision or a clean policy termination
    with a durable ledger and triage report; terminated_policy is not a
    success and not a control-system failure; a $100 cap must mean $100 —
    review rounds, currently unmetered, must debit the same budget, with
    conservative estimates where measurement is impossible.
---

# Plan: Unattended policy core + metering (#191)

## Design

### D1 — Terminal outcomes in the driver
A small outcome layer beside `park()`: `terminate_policy(reason, detail,
evidence...)` writes the ledger (`outcome`, `disposition_reason`, cost
totals incl. estimated), generates `triage-report.md`, attempts the
best-effort artifacts (reusing the existing escalation WIP-push path and
its journaled-failure semantics), notifies, exits **6**. `landed` and
`failed` become explicit ledger outcomes on the existing success/error
paths. `park()` itself is untouched for attended profiles.

### D2 — Disposition dispatch
`dispose(reason, ...)` consulted at every current `park` call site:
profile != unattended → `park` (exact current behavior); unattended →
`terminate_policy`. The mapping is a case table in one place, with
`origin_gate` hard-wired to terminate irrespective of config. Preflight
for `profile: unattended` fails closed ("admission control (increment B
of #190) is not available yet") BEFORE any session runs; tests reach the
dispatch layer via the driver's existing test seams/dry paths.

### D3 — Config v2 + validator
`shared/schemas/automation.schema.json` (JSON Schema draft-07, matching
the repo's schema conventions) + `scripts/validate-automation-config.sh`
(jq-based structural checks mirroring the schema for hosts without a
schema validator; the schema file is the contract, the script is the
enforcement). v2 adds the `unattended` block; enum for the three `on_*`
keys is exactly ["terminate"] in A; `schema_version: 1` documents remain
valid (absent blocks = today's behavior). Driver preflight invokes the
validator; unattended additionally requires explicit `caps.*` (the
validator knows the profile).

### D4 — Cost metering
`review-round-runner.sh`: each reviewer/fix invocation captures its
result cost (same `.total_cost_usd` envelope the driver already parses
where the backend provides it); per-round `cost_usd` lands in the runner
state + `loop-summary.json` (additive fields). The driver reads the
round cost after each review loop and accumulates. Estimate path: an
invocation with no measurable cost debits a conservative constant
(config: `unattended.budget.estimate_unmetered`, default true; estimate
value from the automation config with a documented default), recorded
`estimated: true`. The existing cap check then operates on the combined
total unchanged.

### D5 — Supervisor contract
`cooldown-supervisor.sh` exit classification: 6 → terminal, never
relaunch (regardless of `--on-incomplete`); test added to its suite.

### D6 — Template + docs
`automation-template.json` → schema_version 2 + `unattended` block
(commented defaults); skills docs touched only where behavior is now
real (auto-build-loop SKILL: outcomes table, metering, fail-closed
preflight); README/CHANGELOG per repo convention.

## Deliverables

1. Driver: outcome layer, dispatch, unattended preflight fail-close,
   estimate debits, validator invocation.
2. Runner: per-round cost emission.
3. Schema + validator script; template v2.
4. Supervisor rule + test.
5. Tests across all of the above; docs.

## Sequencing (phases; per-phase review loop as #186/#188/#189)

1. **Phase 1**: schema + validator + template v2 (+ tests) — the contract
   first, everything else validates against it.
2. **Phase 2**: driver outcome layer + dispatch + fail-closed preflight
   (+ parameterized 12-reason test, byte-identical attended assertions).
3. **Phase 3**: metering (runner emission + driver accumulation +
   estimates) and the supervisor rule (+ tests); docs.

## Test strategy

- Validator: accept/reject matrix (v1 valid; v2 valid; on_origin_gate !=
  terminate rejected; recovery values rejected; unattended without
  explicit caps rejected).
- Dispatch: parameterized over all 12 reasons under unattended → ledger
  outcome/reason/exit 6/triage report; attended profiles unchanged
  (existing driver tests must not change).
- Artifacts: termination with a blocked push → mandatory artifacts exist,
  skip journaled, prechecks NOT weakened (assert no force flags).
- Metering: runner summary carries round costs; driver total = build +
  review + fix (+ estimate case, flagged); cap trips on combined total.
- Supervisor: exit 6 never relaunched under --on-incomplete relaunch.
- Regression: full existing suites (auto-build tests, launcher, runtime).

## Leans recorded (proceeding per the established loop; PR review catches
## disagreements)

1. Exit code **6** (0/1/3/4 taken; umbrella suggests "e.g. 6").
2. The A-boundary: `profile: unattended` fails closed at preflight until
   B — direct reading of the umbrella's "Nothing runs unattended before
   B"; tests exercise machinery through seams, not live runs.
3. Validator shape: JSON Schema file as the contract + a jq-based script
   as the enforcement (no new runtime dependency for CI/hosts).
4. Estimate default: a single conservative per-invocation constant in
   config (documented), not a per-provider price table — §12 calibration
   (increment D) refines it.
