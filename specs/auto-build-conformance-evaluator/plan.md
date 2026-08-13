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

# Plan: runtime conformance evaluator, increment C2 (#242) — rev 4

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
| Checkout | evidence in throwaway worktree | in-place, under an empty-porcelain-before/after integrity invariant (untracked files included) |

## Design decisions (normative)

1. **Derivation reads the finalized yaml.** `conformance.required` is
   computed at admission (unattended) and at contract initialisation
   (both profiles) from the statement_sha-validated `verification.yaml`:
   true iff any FR maps to `runtime_conformance`. It is never read from
   config; an operator `required` key is a schema violation.

2. **Admission (unattended) — handoff item 2.** Replace validate-spec's
   categorical `runtime_conformance` refusal with:
   - no mapping → no conformance requirement, block optional, admission
     behavior unchanged;
   - mapping present → require `verification.conformance` with an
     `evaluator` that resolves in providers.toml, DECLARES
     `conformance_command` (decision 8 — rev 4, finding 1), AND passes
     providers-health; otherwise refuse (named check per missing piece,
     exit 1, no ledger). Health alone never admits: a healthy
     reviewer-only provider is refused by name.
   Attended runs have no admission: the same
   resolution+capability+health check runs at the gate and parks
   (`provider_unavailable`) instead.

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
     stop_timeout_sec}, interface, timeout_sec, criteria:
     [ {fr, statement_sha, criterion} … ] }`, present iff derived
     required. `interface` is RESOLVED at freeze (rev 4, finding 2):
     `app.interface` when present, else `ready.url`; a
     command-only-readiness config with neither is rejected by name at
     config validation (both profiles) — a capable evaluator must never
     be launched without an address for the app.
   The preflight-result schema's closed `contract` object accepts both
   new sub-objects as optional CLOSED shapes; `validate_contract_json`
   gains the matching rules. All C1 pinning/tamper/resume-equality rules
   apply to the whole contract object unchanged — no second mechanism.

5. **The landing verifier gate** — ONE normative sequence, AFTER the
   coverage gate and BEFORE finalize/push/PR. Skip entirely iff the
   frozen contract carries neither `verifiers` nor `conformance`.
   1. tamper check (C1's, covers the whole pinned object);
   2. **checkout integrity — BEFORE (rev 3: untracked included):**
      require an EMPTY full porcelain status — tracked AND untracked
      files (an untracked file would otherwise reach `driver_commit`'s
      `git add -A` summary commit) — and capture `GATE_HEAD`;
   3. **execute every frozen deterministic verifier (rev 2, finding
      1):** run each `test` command from the project root, bounded by
      the frozen `timeout_sec`, exit 0 = that verifier green (the
      `metric` is the assertion the target itself implements — the
      driver does not re-parse it in C2); record per-verifier
      {exit, duration, log path}. Admission's resolution was the
      screen; THIS is the decision — a verifier is never inferred green
      from the generic `test.command`;
   4. if the frozen contract carries `conformance`: gate-time
      re-resolution of the frozen evaluator provider — it must still
      resolve, still declare `conformance_command` (rev 4, finding 1),
      and pass health; any miss disposes `provider_unavailable` (whose
      resume arm re-checks all three);
   5. **pre-launch binding probe (rev 3, finding 4):** run the ready
      probe ONCE before launch; it MUST FAIL — an already-answering
      responder cannot be attributed to this launch → dispose
      `conformance_gate` ("ready probe answered before launch"). Then
      start the app: spawn `app.command` in its own process group from
      the project root, capture stdout/stderr to
      `$LEDGER_DIR/conformance/app.log`;
   6. readiness: poll `ready.url` (HTTP 200) or run `ready.command`
      (exit 0) within `ready.timeout_sec`, AND require the spawned
      process group to still be alive at the moment readiness succeeds
      (rev 2, finding 5 — a stale process answering the probe must not
      vouch for a dead launch); failure → stop → dispose
      `conformance_gate` ("app never became ready");
   7. **author the request; invoke through the adapter (rev 3, finding
      2):** providers consume a request document and emit stdout — the
      reviewer protocol; environment variables neither instruct a model
      nor produce files, and providers may be explicitly read-only. The
      driver writes `$LEDGER_DIR/conformance/request.md` from the
      FROZEN contract: the criteria tuples
      `[ {fr, statement_sha, criterion} … ]`, the FROZEN app
      `interface` (decision 4 — the resolved address of the running
      app; nothing mutable), and a Required Output Format
      section demanding EXACTLY ONE fenced JSON block
      `{ "criteria": [ {fr, statement_sha, criterion, verdict,
      evidence} … ] }`. ENSURE the result path is absent (freshness,
      the C1 delete-before-run lesson); substitute the request path at
      the provider's `conformance_command` template's request-file
      placeholder (decision 8; the `{review_request}` slot is reused as
      the generic request-file slot); the
      adapter captures stdout bounded by the frozen `timeout_sec` and
      writes `CCT_REVIEW_COST_FILE`; the ADAPTER extracts the fenced
      JSON block from the capture and writes it to the result path —
      the evaluator itself writes nothing (read-only providers are
      admissible). Non-zero exit, timeout, or no/multiple fenced blocks
      = evaluator failure;
   8. stop the app: TERM the process group, escalate to KILL after
      `stop_timeout_sec` (cp_run_bounded's escalation-must-complete
      discipline);
   9. **checkout integrity — AFTER (rev 3: untracked included):**
      require HEAD == `GATE_HEAD` and an EMPTY full porcelain status
      (tracked AND untracked files); any mutation is a control-system
      failure — dispose `git_anomaly` naming the paths, and the
      mutation must never reach the `git add -A` summary commit;
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

8. **The evaluator capability is an explicit command contract (rev 4,
   finding 1).** providers.toml entries gain an optional
   `conformance_command` — an evaluator-specific command template
   (request-file placeholder; the entry's existing `healthcheck` and
   `timeout_sec` semantics apply). Declaring it IS the
   `runtime_conformance` capability: reviewer health proves liveness,
   not the ability to exercise a running application (a read-only
   review profile or a plain prompt-in/text-out adapter passes health
   yet can only fabricate runtime evidence). The operator grants the
   template whatever flags/tooling app-exercising needs — the review
   `command`'s read-only, .git-stripped sandbox assumptions do not
   transfer. The driver never invokes a review `command` as an
   evaluator; `provider-profile-template.toml` documents the field.

## Deliberately NOT in this slice

Visual/`skip_is_failure` (#239, C3); §5 bounded progress and any
multi-round evaluator loop (single invocation per landing gate); §7
per-phase contracts; §13/D recovery; the admission DEFER items
"schema-migration allowlist" and "mid-flight credential/secret
enumeration" (unowned — recorded on #242); evaluator sandboxing beyond
the app process-group containment (the evaluator is a trusted configured
provider, same trust class as reviewers).

## Risk and the scope of "byte-identical"

Runs with NEITHER a coverage block NOR a finalized `verification.yaml`
MUST behave byte-identically to C1 — asserted the C1 way (neither-input
fixtures re-run against the new driver). Two intentional behavior
changes for existing configs, both documented and tested (rev 3,
finding 1 — the rev-2 "byte-identical, no changes" claim was wrong):
1. deterministic verifiers of a finalized artifact are EXECUTED at the
   landing gate (SC-8) — previously admission screened them and landing
   keyed only on the generic `test.command`, so a run whose verifier
   command fails can NEWLY block landing;
2. a finalized artifact now triggers the frozen-contract lifecycle
   (`-block` preflight paths, decision 3 — SC-3).
`runtime_conformance` mappings were inadmissible before C2, so no
admitted run can have depended on the old refusal.

## Test strategy

Driver-suite e2e per SC (fixtures: a stub evaluator provider registered
in the REAL provider-template shape — declaring `conformance_command`
with the request-file placeholder — emitting the fenced JSON verdict
block on stdout; a healthy reviewer-only provider entry for the
capability-refusal cases; a stub app with ready endpoint and a marker
child for the process-group assertion; a pre-existing responder for the
pre-launch binding probe), validate-spec admission cases, schema parity
assertions, pi runtime untouched (no pi surface in C2), mutation runs
for every SC regression (C1 discipline).
