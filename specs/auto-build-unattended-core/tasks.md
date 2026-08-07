# Tasks: Unattended policy core + metering (#191, Increment A of #190)

Terminate-only increment — no admission (B), no verification contract
(C), no recovery (D). Attended profiles byte-identical; nothing runs
unattended (fail-closed preflight until B). Targets **#191**; must not
close umbrella **#190**. `SC` = success criterion in `spec.md`.

## Phase 1 — Contract first: schema + validator

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 1 | | `shared/schemas/automation.schema.json`: v2 with the `unattended` block; `on_review_breaker`/`on_stale_finding`/`on_origin_gate` enum = ["terminate"] in A; v1 (absent blocks) valid. | `shared/schemas/` | SC-5 |
| 2 | | `scripts/validate-automation-config.sh`: jq-based enforcement of the schema contract incl. profile-aware explicit-caps rule for `unattended`; clear per-violation errors; exit codes per repo convention. | `scripts/` | SC-1/3/5 |
| 3 | | `automation-template.json` → schema_version 2 + commented `unattended` block; per-increment note that recovery values arrive later. | `shared/templates/sdd/` | SC-5 |
| 4 | | Validator tests: accept/reject matrix (v1 valid, v2 valid, origin-gate lock, recovery values rejected, missing explicit caps under unattended rejected, malformed JSON). | `tests/` | SC-1/3/5 |

## Phase 2 — Driver: outcomes + dispatch

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 5 | | Outcome layer: `terminate_policy()` (ledger outcome/reason/evidence + cost totals incl. estimated, `triage-report.md`, best-effort commit/push/draft-PR via existing precheck-respecting paths with journaled skips, notify, exit 6); explicit `landed`/`failed` ledger outcomes on existing paths. | `scripts/auto-build-loop.sh` | SC-1 |
| 6 | | `dispose()` at every park call site: attended → `park` (byte-identical), unattended → terminate; `origin_gate` hard-wired terminate regardless of config; profile ladder gains `unattended`; preflight fails closed naming the missing B admission gate; validator invoked at preflight. | `scripts/auto-build-loop.sh` | SC-1/2 |
| 7 | | Tests: parameterized 12-reason termination (ledger/report/exit 6), fail-closed preflight, attended byte-identical regressions, blocked-push artifact case (mandatory artifacts + journaled skip + no precheck weakening). | `tests/` | SC-1/2 |

## Phase 3 — Metering + supervisor + docs

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 8 | | Runner cost emission: per reviewer/fix invocation where the backend reports cost; per-round `cost_usd` in state + `loop-summary.json` (additive). | `scripts/review-round-runner.sh` | SC-3 |
| 9 | | Driver accumulation: review/fix round costs debit `.totals.cost_usd`; unmeterable → conservative estimate (config default, documented) flagged `estimated: true`; cap check on the combined total; unmeterable-and-unestimable = preflight error. | `scripts/auto-build-loop.sh` | SC-3 |
| 10 | | Supervisor: exit 6 terminal (never cooldown/relaunch/reclassify) + test in its exit-classification suite. | `scripts/cooldown-supervisor.sh`, `tests/` | SC-4 |
| 11 | [P] | Docs: auto-build-loop SKILL outcomes/metering/fail-closed table; README/CHANGELOG lines; #190 umbrella comment pointing at the increment. | skills, docs | SC-5 |

## Global definition of done

Attended profiles byte-identical (regression-asserted) · exit 6 distinct
from 4, `--resume` untouched · origin_gate terminate-only schema-enforced
· no admission/verification/recovery machinery (B/C/D) · security floors
untouched · every driver-initiated invocation metered or conservatively
estimated against the SAME cap · all suites green · per-phase review loop
· targets **#191**, leaves **#190** open.
