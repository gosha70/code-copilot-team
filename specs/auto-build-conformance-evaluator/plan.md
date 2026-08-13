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

# Plan: runtime conformance evaluator, increment C2 (#242) — rev 1

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

| Concern | C1 (coverage) | C2 (conformance) |
|---|---|---|
| Config | `verification.coverage` | `verification.conformance` accepted; `required` rejected by name (derived) |
| Frozen at preflight | coverage contract | + optional `conformance` sub-object (evaluator, app contract, criteria set) |
| Evidence | cp_collect in throwaway worktree | evaluator invocation against the driver-launched app |
| Gate point | `floor_enforced_at` (phase/landing) | landing only (single invocation; §5 loops deferred) |
| Disposition | `coverage_gate` | `conformance_gate` (same parked_head + recovery contract) |
| Metering | n/a (local commands) | reviewer-style cost channel + estimates |

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

3. **Freezing.** The contract initialiser (T5 machinery) adds, when the
   requirement is derived true, a `conformance` sub-object to the frozen
   contract: `{ evaluator, app: {command, ready, stop_timeout_sec},
   timeout_sec, criteria: [ {fr, statement_sha, criterion} … ] }`. The
   preflight-result schema's `contract` object accepts it as an optional
   CLOSED sub-object; `validate_contract_json` gains the matching rules.
   All C1 pinning/tamper/resume-equality rules apply to the whole
   contract object unchanged — no second mechanism.

4. **The landing conformance gate**, in order, AFTER the coverage gate
   and BEFORE finalize/push/PR:
   1. skip unless the frozen contract carries `conformance`;
   2. tamper check (C1's, already covers the whole pinned object);
   3. gate-time health check of the frozen evaluator provider →
      unhealthy disposes `provider_unavailable`;
   4. worktree prune (FR-8 honest trigger does NOT apply — no throwaway
      worktree here; the app runs from the committed checkout in place.
      The evaluator must see the app AS IT WILL LAND: HEAD is committed
      at this point, tree is clean);
   5. start the app: spawn `app.command` in its own process group from
      the project root, capture stdout/stderr to
      `$LEDGER_DIR/conformance/app.log`;
   6. readiness: poll `ready.url` (HTTP 200) or run `ready.command`
      (exit 0) within `ready.timeout_sec`; timeout → stop the app →
      dispose `conformance_gate` ("app never became ready");
   7. write the criteria file from the FROZEN criteria; invoke the
      evaluator provider (reviewer invocation path) with
      `CCT_CONFORMANCE_CRITERIA`, `CCT_CONFORMANCE_RESULT`,
      `CCT_REVIEW_COST_FILE`, bounded by the frozen `timeout_sec`;
   8. stop the app: TERM the process group, escalate to KILL after
      `stop_timeout_sec` (cp_run_bounded's escalation-must-complete
      discipline);
   9. debit costs (measured via the cost file, else estimate);
   10. validate the result file: parseable, schema-shaped, exactly the
       frozen criteria covered — anything else is evaluator FAILURE
       (fail closed);
   11. write `verification-results.json` (FR-7): every FR of the frozen
       artifact — deterministic entries green iff the final test gate
       passed; conformance entries from the verdicts;
   12. any non-green entry → dispose `conformance_gate` naming the
       FR(s); then `check_caps`.

5. **Dispositions.** `conformance_gate` joins the dispose taxonomy with
   the C1 recovery contract verbatim: parks record `parked_head`; the
   generic/coverage recovery arms' commit-bound review applies through a
   shared arm (the existing `coverage_gate` resume arm generalises to
   both reasons — one arm, two reason labels). `terminated_policy` triage
   names the failing FR(s).

6. **Metering (items 3/5).** The evaluator is invoked through the same
   adapter wrapper reviewers use, so `CCT_REVIEW_COST_FILE` is written by
   the adapter, not parsed from output. `debit_review_costs` is reused
   with a `conformance` label. Estimates: the reviewer per-invocation
   estimate applies when active.

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
