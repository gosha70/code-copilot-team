# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-09 03:00
Trigger: plan.md, spec.md and tasks.md revised to rev 7 after the user's
sixth review round; the rev-6 record is stale.

## Origin sources read

- #222, #190 §6, the increment-C handoff notes.
- The user's sixth-round findings (residual admission ownership; a schema
  that cannot enforce its own table).

## Working claim

Scope unchanged since rev 2. Rev 7 completes the ownership change by
enumeration and gives the result file a `path` discriminator with closed
`oneOf` branches, so the emission table is enforced by the schema instead of
by the driver's memory.

## Mismatches

- #222's `skip_is_failure` remains deliberately unmet (C3); #222 stays open.

## What rev 7 changed, per finding

1. **The admission→preflight ownership change still was not global**, in
   US2, FR-4, FR-7, SC-2, T4b, the plan's freeze paragraph, and SC-5d's
   stale field name. This is the THIRD round in which the same propagation
   failed, so rev 7 did it by enumeration: grep every line where admission
   is the actor for contract or baseline work, fix each, then re-grep and
   justify every survivor (all remaining hits are the `baseline: admission`
   config VALUE, the pre-admission timestamp, and the prune trigger — none
   assign ownership). FR-4 now says explicitly that the value `admission`
   names the point in the run, not the actor, which is what made the stale
   readings look plausible.
2. **The schema could not enforce the seven-path table.** `mode` plus two
   optional sections cannot see profile or block presence, so it could not
   distinguish fresh-unattended-with-block (both sections required) from
   fresh-unattended-no-block (admission only), and `{schema_version, mode}`
   would have validated as an empty result — meaning a fresh unattended
   coverage run could return accounting with no contract and pass. The
   discriminator is now the PATH, with closed `oneOf` branches per path, and
   the driver independently computes the expected path and rejects
   disagreement. The "no file" rows are now literal: no result path is
   allocated when no producer runs, rather than an empty placeholder that
   would later need distinguishing from a real result.

## Verdict

Verdict: aligned
Confidence: high
