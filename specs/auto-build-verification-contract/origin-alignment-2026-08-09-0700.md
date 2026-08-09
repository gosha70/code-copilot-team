# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-09 07:00
Trigger: plan.md, spec.md and tasks.md revised to rev 13 after the user's
twelfth review round; the rev-12 record is stale.

## Origin sources read

- #222, #190 §6, the increment-C handoff notes.
- The user's twelfth-round findings (timeout not frozen, attended warning
  leaves an unbounded path, sequence omits the re-check).

## Working claim

Scope unchanged since rev 2. Rev 13 adds `timeout_sec` to the authoritative
frozen-contract field list and canonical example, refuses an unenforceable
bound on both profiles, and enumerates the post-command containment re-check
as a numbered step in the executable sequence.

## Mismatches

- #222's `skip_is_failure` remains deliberately unmet (C3); #222 stays open.

## What rev 13 changed, per finding

1. **`timeout_sec` was required but not frozen.** FR-4a enumerated every
   frozen field and omitted it, as did the canonical example — so an
   implementation could satisfy FR-5c at initialisation and then run
   unbounded at a later gate or on resume, or have the bound widened by a
   live edit. It is now in the field list, the example, tasks, and SC-5n
   asserts config/preset/`test.timeout_sec` edits cannot move it.
2. **The attended path was left unbounded.** FR-5d refused unattended runs
   but only warned for attended, contradicting FR-5c's "every capture and
   gate" — and an attended brownfield initialiser runs the same arbitrary
   command and hangs the same way. Refusal now applies to any
   coverage-enabled run on either profile; no-block runs stay untouched, so
   FR-2 is unaffected.
3. **The executable sequence omitted the re-check** the heading promised.
   Since the plan says implementations follow these steps literally, the
   TOCTOU could have been reintroduced from a document that claims to have
   fixed it. The sequence is now seven numbered steps with the second
   containment resolution at step 5, explicitly before any stat or read.

## Verdict

Verdict: aligned
Confidence: high
