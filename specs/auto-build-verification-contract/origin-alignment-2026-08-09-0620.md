# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-09 06:20
Trigger: plan.md, spec.md and tasks.md revised to rev 12 after the user's
eleventh review round; the rev-11 record is stale.

## Origin sources read

- #222, #190 §6, the increment-C handoff notes.
- The user's eleventh-round findings (post-execution containment, unbounded
  coverage command, optional brownfield threshold).

## Working claim

Scope unchanged since rev 2. Rev 12 re-resolves containment after the
command exits, bounds the coverage command with a frozen timeout that
refuses rather than degrades where unenforceable, and makes an effective
`max_regression_pct` mandatory for brownfield while defining exactly which
metrics it governs.

## Mismatches

- #222's `skip_is_failure` remains deliberately unmet (C3); #222 stays open.

## What rev 12 changed, per finding

1. **My rev-11 containment fix created a TOCTOU.** Checking realpath before
   the command is not enough: the command is arbitrary project code and can
   replace a safe ancestor with an out-of-tree symlink between the check and
   the read. Containment is now re-resolved after exit and before parsing,
   and SC-5j asserts the command-CREATED symlink case, not only a
   pre-existing one.
2. **The coverage command was unbounded.** The wall-clock cap is only
   evaluated between operations, so a hanging command blocks an unattended
   run indefinitely. The frozen contract now carries a positive
   `timeout_sec`. FR-5d additionally refuses rather than degrades where no
   timeout mechanism exists — this repo demonstrably has such hosts, and
   #205 already showed a `timeout_sec` that enforced nothing.
3. **"Only when brownfield" read as permitted, not required**, leaving
   FR-4's no-regression promise unbacked. An effective value (config or
   preset) is now required for brownfield and inadmissible without one, and
   the governed metrics are defined: exactly those with a configured floor,
   so declaring a floor never silently activates an unrelated gate.

## Verdict

Verdict: aligned
Confidence: high
