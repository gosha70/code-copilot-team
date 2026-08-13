# Tasks: runtime conformance evaluator, increment C2 (#242) — rev 3

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

## T3 — Frozen verification contract + lifecycle rekey (FR-4)

- Contract initialiser: derive the requirement; freeze `verifiers`
  (the deterministic set `{fr, statement_sha, test, metric}` +
  `timeout_sec`) and `conformance{evaluator, app, timeout_sec,
  criteria[]}` into the contract object alongside coverage.
- **Lifecycle/path change (plan decision 3):** introduce
  `HAS_FROZEN_CONTRACT = HAS_COVERAGE_BLOCK || HAS_VERIFICATION_ARTIFACT`
  and rekey `compute_preflight_path`, the resume frozen-contract
  prerequisite, the fresh-refusal ledger rollback, and the
  contract-initialiser trigger on it. Runs with neither input stay
  byte-identical noblock.
- `preflight-result.schema.json` optional closed `verifiers` +
  `conformance` sub-objects; `validate_contract_json` rules; C1
  pinning/tamper/resume equality untouched (they cover the whole
  object).
- Tests in `test-auto-build-loop.sh` (freeze shape, edit-immunity,
  tamper disposes, conformance-only `-block` path + resume refusal —
  SC-3).

## T4 — App lifecycle (FR-6)

- Pre-launch binding probe (the ready probe MUST fail before launch),
  start in own process group, ledger-captured output, ready probe
  (url/command, bounded, AND the spawned group alive at success), stop
  with TERM→KILL escalation that must complete (cp_run_bounded
  discipline).
- Tests: a pre-existing responder answering `ready.url` before launch
  fails the gate (launched command = sleep marker); ready-timeout fails
  closed; readiness with a dead spawned group fails closed; no
  descendant survives the gate (marker child) — SC-5.

## T5 — Landing verifier gate + evidence (FR-5, FR-7, FR-9, FR-11)

- The plan's 12-step landing sequence: tamper check; checkout integrity
  BEFORE (EMPTY full porcelain status incl. untracked, capture gate
  HEAD); EXECUTE every frozen deterministic verifier (bounded,
  per-verifier results — never inferred from `test.command`); evaluator
  health check; pre-launch binding probe + app up; driver-authored
  conformance request document (frozen criteria tuples + app interface
  + Required Output Format: exactly one fenced JSON verdict block);
  ensure-absent → bounded provider invocation via the request-file
  placeholder, adapter-captured stdout → the ADAPTER extracts the block
  and writes the result file (the evaluator writes nothing; read-only
  providers admissible); app stop; checkout integrity AFTER (HEAD
  unchanged + EMPTY porcelain incl. untracked, else `git_anomaly`);
  fail-closed identity-multiset result validation (full-tuple echo);
  `verification-results.json` FR → per-verifier results;
  `conformance_gate` disposition naming FRs/verifiers, shared
  commit-bound recovery arm (generalise the coverage arm to both
  reasons), attended parity.
- Tests: SC-4, SC-7, SC-8, SC-9 (tracked-edit AND untracked-file
  mutations); the evaluator stub registered in the real
  provider-template shape; neither-input byte-identical fixtures.

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
