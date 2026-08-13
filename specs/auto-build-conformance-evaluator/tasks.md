# Tasks: runtime conformance evaluator, increment C2 (#242)

Sequenced; each task lands with its regressions and mutation runs. The
plan's gate sequence is normative.

## T1 — Config surface + derivation (FR-1, FR-2)

- `automation.schema.json`: accept `verification.conformance`
  (closed: `evaluator`, `app{command, ready{url|command, timeout_sec},
  stop_timeout_sec}`, `timeout_sec`); reject `required` by name;
  `test`/top-level `app`/`visual` stay rejected.
- `validate-automation-config.sh` parity with the schema.
- Derivation helper: `required` iff the finalized `verification.yaml`
  maps any FR to `runtime_conformance` (reads the sha-validated
  artifact).
- Tests in `test-automation-config.sh` + schema parity assertions.

## T2 — Admission flip (FR-3, handoff item 2)

- `validate-spec.sh --unattended`: replace the categorical
  `runtime_conformance` refusal with the availability check
  (block present, provider resolves, providers-health passes); named
  refusal messages per missing piece; no-mapping runs unchanged.
- Tests in `test-verification-spec.sh` (admit/refuse matrix, SC-1).

## T3 — Frozen conformance contract (FR-4)

- Contract initialiser: derive the requirement; freeze
  `conformance{evaluator, app, timeout_sec, criteria[]}` into the
  contract object alongside coverage.
- `preflight-result.schema.json` optional closed `conformance`
  sub-object; `validate_contract_json` rules; C1 pinning/tamper/resume
  equality untouched (they cover the whole object).
- Tests in `test-auto-build-loop.sh` (freeze shape, edit-immunity,
  tamper disposes — SC-3).

## T4 — App lifecycle (FR-6)

- Start in own process group, ledger-captured output, ready probe
  (url/command, bounded), stop with TERM→KILL escalation that must
  complete (cp_run_bounded discipline).
- Tests: ready-timeout fails closed; no descendant survives the gate
  (marker child) — SC-5.

## T5 — Evaluator invocation + landing gate + evidence (FR-5, FR-7, FR-9)

- The plan's 12-step landing sequence: health check, app up, criteria
  file from frozen set, bounded evaluator invocation via the reviewer
  adapter path, fail-closed result validation, verification-results.json
  per FR, `conformance_gate` disposition naming FRs, shared commit-bound
  recovery arm (generalise the coverage arm to both reasons), attended
  parity.
- Tests: SC-4, SC-7; byte-identical no-block fixtures.

## T6 — Metering (FR-8, handoff items 3/5)

- Cost-file channel through the reviewer adapter wrapper; measured vs
  estimate debits with `conformance` labels; `check_caps` after the
  gate; in-band text never parsed.
- Tests: SC-6 (measured, unmetered/estimate, cap-cross event order).

## T7 — Docs + gates

- README (conformance section beside the coverage contract), CHANGELOG,
  schema descriptions, count pins.
- Record on #242: DEFER items (c)/(d) remain unowned; #190 stays open
  for C3 (#239) and D.
- Full sweep; every SC regression verified to fail against pre-change
  code.
