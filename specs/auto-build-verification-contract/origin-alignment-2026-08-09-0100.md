# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-09 01:00
Trigger: plan.md and spec.md revised to rev 4 after the user's third review
round; the rev-3 record is stale.

## Origin sources read

- #222, #190 §6, the increment-C handoff notes.
- The user's third-round findings, and their proposed state-machine split.

## Working claim

Unchanged in scope from rev 3 — `verification.coverage` only, everything
else rejected or deferred. Rev 4 adds the missing RUN LIFECYCLE: explicit
fresh and resume sequences, a frozen contract that includes its own
`command`, resume that validates rather than re-decides, a timestamped
`reset_run_clocks()`, a pending-event buffer, and a byte-identical promise
narrowed to attended runs with two enumerated unattended exceptions.

## Mismatches

- #222's `skip_is_failure` remains deliberately unmet (C3); #222 stays open.

## What rev 4 changed, per finding

1. **The frozen contract could not run coverage.** It omitted `command`
   while T6 said gates read only the frozen block — impossible as written.
   `command` is now frozen with the rest.
2. **Resume would have recaptured the baseline.** `load_config()` reruns
   admission on every non-terminal resume, so without a distinct contract
   the resume would import a fresh result computed from the CURRENT branch
   against the LIVE preset — defeating exactly the freezing rev 3 added.
   Resume now loads and schema-validates the existing contract, never
   recaptures, and fails closed when it is missing or corrupt.
3. **Resume would have erased admission time again.** `reset_run_clocks()`
   sets `started_epoch` to *now* and runs after admission on the resume
   path, reintroducing FR-9's bug on every resume. It now takes an explicit
   timestamp; existing callers pass `now`.
4. **Prune journalling contradicted no-ledger-on-refusal.** `journal()`
   writes into the ledger directory, which does not exist before admission
   — and creating it would leave durable state behind a refused admission.
   Pre-ledger events are buffered and flushed after init; stderr on refusal.
5. **"Byte-identical" was too broad.** Unattended runs now prune and count
   admission time even without the block. The promise is narrowed to
   attended runs, with those two enumerated as deliberate exceptions —
   claiming otherwise would have been exactly the overclaim pattern this
   arc keeps surfacing.

The reviewer's framing is adopted directly: the fresh/resume split is now
the plan's backbone, because four of these five were symptoms of its
absence rather than independent defects.

## Verdict

Verdict: aligned
Confidence: high
