# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-09 00:20
Trigger: plan.md and spec.md revised to rev 3 after the user's second review
round; the rev-2 record is stale.

## Origin sources read

- #222, #190 §6, and the recorded increment-C handoff notes.
- The user's second-round findings (preset freezing, wall-clock semantics,
  coverage schema precision, prune vs byte-identical).

## Working claim

C1 delivers `verification.coverage` only, with the FULLY RESOLVED contract
frozen at admission (preset id + file hash, parser, artifact, effective
floors, regression limit, enforcement point, baseline), a driver-owned
result-file channel, a pre-admission timestamp that puts admission inside
the wall-clock budget, and a prune scoped to the unattended admission path.
Everything else is rejected by name or deferred to C2/C3.

## Mismatches

- #222's `skip_is_failure` criterion remains deliberately unmet (C3), as
  agreed in the previous round. #222 stays open.

## What rev 3 changed, per finding

1. **Freezing the preset NAME was insufficient** — the file stays live, so
   an edit or upgrade between admission and landing/resume moves the floor
   under an admitted run. Admission now freezes the fully resolved contract
   including `preset_sha256`, and the gates read only that. Same class as
   #193's config snapshot and #201's mid-run cap raise.
2. **Recording duration is not enforcement.** `totals.started_epoch` is set
   after admission, so a logged `duration_sec` changed no cap arithmetic —
   bookkeeping dressed as a gate, which is the inert-config trap in another
   costume. A pre-admission timestamp now initialises the ledger clock. The
   driver also owns the result-file path and schema-validates it rather than
   scraping it from diagnostic output (the #220 proxy-output lesson).
3. **The coverage contract is now fully specified**: required keys,
   0-100 ranges, at-least-one-floor, `max_regression_pct` REJECTED under
   `baseline: none` (inert otherwise), artifact path containment, and
   regression defined explicitly as percentage POINTS. A floor whose metric
   the artifact cannot supply fails closed rather than passing by absence.
4. **Prune scoped** to the unattended admission path, immediately before
   admission creates the worktree that leaks — so FR-2's byte-identical
   promise holds. Failure is non-fatal and journalled; killing a run over
   housekeeping is the worse trade.

## Verdict

Verdict: aligned
Confidence: high
