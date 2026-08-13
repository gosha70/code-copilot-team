---
spec_mode: full
feature_id: auto-build-conformance-evaluator
status: draft
date: 2026-08-13
risk_category: integration
justification: >
  Executes a configured provider against a running application inside the
  autonomous driver's landing gate, extends the frozen-contract schema,
  and changes admission semantics — integration risk across the driver,
  admission, providers, and the app under build.
origin:
  type: issue
  issue: 242
  parent: 190
  references:
    - "#190 §6 (runtime spec-conformance evaluator), §3 (verification.yaml rules), §2 (metering)"
    - "specs/auto-build-admission/spec.md — Increment-C handoff notes (items 1/2/5)"
    - "specs/auto-build-verification-contract/plan.md — 'Deliberately NOT in this slice' (C2 enumeration)"
  origin_claim: |
    #190 §6 defines a fresh-context evaluator that exercises the running
    application against runtime_conformance verifiers; `required` is
    derived from verification.yaml, never operator-set; admission fails a
    mapped requirement whose evaluator is disabled or unavailable; landed
    requires every mapped verifier green. Handoff items: (1) C owns the
    real verifier decision, (2) the inadmissible check flips to
    evaluator-available-and-healthy, (5) evaluator invocations get the
    adapter cost-channel treatment (with item 3's evaluator-accounting
    remainder).
---

# Plan: runtime conformance evaluator, increment C2 (#242) — rev 2

`spec.md` states the requirements; THIS file's lifecycle additions and
sequences are the normative implementation contract. One source: the C1
plan's per-path table stays authoritative for everything C1 built; C2
adds rows/steps ONLY where named below.

## What exists (C1) and what C2 adds

C1 froze the coverage contract and built the gate machinery: preflight
initialiser, in-memory pinning + tamper rules, worktree-isolated
evidence, park/terminate dispositions with commit-bound recovery, prune
at every creation site. C2 adds a SECOND verification dimension using the
same skeleton:

| Concern | C1 (coverage) | C2 (verifiers + conformance) |
|---|---|---|
| Config | `verification.coverage` | `verification.conformance` accepted; `required` rejected by name (derived) |
| Frozen at preflight | coverage contract | + optional `verifiers` (deterministic set) and `conformance` (evaluator, app, criteria) sub-objects |
| Evidence | cp_collect in throwaway worktree | each frozen deterministic verifier EXECUTED; evaluator invocation against the driver-launched app |
| Gate point | `floor_enforced_at` (phase/landing) | landing only (single invocation; §5 loops deferred) |
| Disposition | `coverage_gate` | `conformance_gate` (same parked_head + recovery contract) |
| Metering | n/a (local commands) | reviewer-style cost channel + estimates |
| Checkout | evidence in throwaway worktree | in-place, under a clean-before/clean-after integrity invariant |

## Design decisions (normative)

1. **Derivation reads the finalized yaml.** `conformance.required` is
   computed at admission (unattended) and at contract initialisation
   (both profiles) from the statement_sha-validated `verification.yaml`:
   true iff any FR maps to `runtime_conformance`. It is never read from
   config; an operator `required` key is a schema violation.

2. **Admission (unattended) — handoff item 2.** Replace validate-spec's
   categorical `runtime_conformance` refusal with:
   - no mapping → no conformance requirement, block optional, C1
     behavior byte-identical;
   - mapping present → require `verification.conformance` with an
     `evaluator` that resolves in providers.toml AND passes
     providers-health; otherwise refuse (named check, exit 1, no ledger).
   Attended runs have no admission: the same availability check runs at
   the gate and parks (`provider_unavailable`) instead.

3. **The lifecycle predicate is verification-wide (rev 2, finding 2).**
   C1's paths keyed on `HAS_COVERAGE_BLOCK`; that predicate no longer
   spans the contract. Define
   `HAS_FROZEN_CONTRACT = HAS_COVERAGE_BLOCK || HAS_VERIFICATION_ARTIFACT`
   where `HAS_VERIFICATION_ARTIFACT` = a finalized
   `specs/<feature>/verification.yaml` exists. `compute_preflight_path`,
   the resume prerequisite (frozen contract REQUIRED on resume whenever
   either input was true at freeze), the fresh-refusal ledger rollback,
   and the contract-initialiser trigger all key on the new predicate. A
   conformance-only (or verifier-only) run therefore takes a `-block`
   path: no silent skip is representable, because the landing gates key
   on the FROZEN sections, and freezing is now guaranteed whenever the
   inputs exist. Runs with neither input remain byte-identical noblock.

4. **Freezing composes three optional sections.** The contract
   initialiser (T5 machinery) writes, per input present:
   - `coverage` — C1, unchanged;
   - `verifiers` — every deterministic verifier of the finalized
     artifact: `[ {fr, statement_sha, test, metric} … ]` plus a single
     `timeout_sec` (from `verification.test.timeout_sec`, else
     `test.timeout_sec`, the FR-5c fallback chain);
   - `conformance` — `{ evaluator, app: {command, ready,
     stop_timeout_sec}, timeout_sec, criteria: [ {fr, statement_sha,
     criterion} … ] }`, present iff derived required.
   The preflight-result schema's closed `contract` object accepts both
   new sub-objects as optional CLOSED shapes; `validate_contract_json`
   gains the matching rules. All C1 pinning/tamper/resume-equality rules
   apply to the whole contract object unchanged — no second mechanism.

5. **The landing verifier gate** — ONE normative sequence, AFTER the
   coverage gate and BEFORE finalize/push/PR. Skip entirely iff the
   frozen contract carries neither `verifiers` nor `conformance`.
   1. tamper check (C1's, covers the whole pinned object);
   2. **checkout integrity — BEFORE (rev 2, finding 4):** require a
      clean tracked tree (the C1 preflight invariant re-checked here)
      and capture `GATE_HEAD`;
   3. **execute every frozen deterministic verifier (rev 2, finding
      1):** run each `test` command from the project root, bounded by
      the frozen `timeout_sec`, exit 0 = that verifier green (the
      `metric` is the assertion the target itself implements — the
      driver does not re-parse it in C2); record per-verifier
      {exit, duration, log path}. Admission's resolution was the
      screen; THIS is the decision — a verifier is never inferred green
      from the generic `test.command`;
   4. if the frozen contract carries `conformance`: gate-time health
      check of the frozen evaluator provider → unhealthy disposes
      `provider_unavailable`;
   5. start the app: spawn `app.command` in its own process group from
      the project root, capture stdout/stderr to
      `$LEDGER_DIR/conformance/app.log`;
   6. readiness: poll `ready.url` (HTTP 200) or run `ready.command`
      (exit 0) within `ready.timeout_sec`, AND require the spawned
      process group to still be alive at the moment readiness succeeds
      (rev 2, finding 5 — a stale process answering the probe must not
      vouch for a dead launch); failure → stop → dispose
      `conformance_gate` ("app never became ready");
   7. write the criteria file from the FROZEN criteria and the
      evaluator-visible app interface `CCT_CONFORMANCE_APP` (rev 2,
      finding 5): a JSON artifact carrying the frozen app contract's
      evaluator-relevant fields (`ready.url` when present — the base
      URL of the running app — plus nothing mutable); ENSURE the result
      path is absent (freshness, the C1 delete-before-run lesson);
      invoke the evaluator provider (reviewer invocation path) with
      `CCT_CONFORMANCE_CRITERIA`, `CCT_CONFORMANCE_RESULT`,
      `CCT_CONFORMANCE_APP`, `CCT_REVIEW_COST_FILE`, bounded by the
      frozen `timeout_sec`; require invocation completion and require
      the result file to be NEWLY produced;
   8. stop the app: TERM the process group, escalate to KILL after
      `stop_timeout_sec` (cp_run_bounded's escalation-must-complete
      discipline);
   9. **checkout integrity — AFTER (rev 2, finding 4):** require HEAD
      == `GATE_HEAD` and the tracked tree clean; any mutation is a
      control-system failure — dispose `git_anomaly` naming the paths,
      and the mutation must never reach the summary commit;
   10. debit costs (measured via the cost file, else estimate);
   11. validate the result: parseable, schema-shaped, and an EXACT
       identity multiset match against the frozen criteria (rev 2,
       finding 3): every verdict echoes its full frozen tuple
       `{fr, statement_sha, criterion}` plus `{verdict, evidence}`, and
       no criterion may be missing, duplicated, phantom, or modified —
       anything else is evaluator FAILURE (fail closed);
   12. write `verification-results.json` (FR-7): FR → PER-VERIFIER
       results (deterministic executions from step 3; conformance
       verdicts from step 11); an FR is green iff ALL its mapped
       verifiers are green; any non-green or unresolved entry →
       dispose `conformance_gate` naming FR(s) and verifier(s); then
       `check_caps`.

6. **Dispositions.** `conformance_gate` joins the dispose taxonomy with
   the C1 recovery contract verbatim: parks record `parked_head`; the
   commit-bound recovery applies through a shared arm (the existing
   `coverage_gate` resume arm generalises — one arm, two reason labels).
   `terminated_policy` triage names the failing FR(s)/verifier(s).

7. **Metering (items 3/5).** The evaluator is invoked through the same
   adapter wrapper reviewers use, so `CCT_REVIEW_COST_FILE` is written by
   the adapter, not parsed from output. `debit_review_costs` is reused
   with a `conformance` label. Estimates: the reviewer per-invocation
   estimate applies when active. Deterministic verifier executions are
   local commands (unmetered, like `test.command`), but their wall-clock
   counts — `check_caps` closes the gate.

## Deliberately NOT in this slice

Visual/`skip_is_failure` (#239, C3); §5 bounded progress and any
multi-round evaluator loop (single invocation per landing gate); §7
per-phase contracts; §13/D recovery; the admission DEFER items
"schema-migration allowlist" and "mid-flight credential/secret
enumeration" (unowned — recorded on #242); evaluator sandboxing beyond
the app process-group containment (the evaluator is a trusted configured
provider, same trust class as reviewers).

## Risk and the scope of "byte-identical"

Runs without a conformance requirement MUST behave byte-identically to
C1 — asserted the C1 way (no-block fixtures re-run against the new
driver). The only intentional behavior changes for existing configs:
none — `runtime_conformance` mappings were inadmissible before C2, so no
admitted run can have depended on the old refusal.

## Test strategy

Driver-suite e2e per SC (fixtures: a stub evaluator provider writing
verdict files; a stub app with ready endpoint and a marker child for the
process-group assertion), validate-spec admission cases, schema parity
assertions, pi runtime untouched (no pi surface in C2), mutation runs
for every SC regression (C1 discipline).
