# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-09 05:00
Trigger: plan.md, spec.md and tasks.md revised to rev 10 after the user's
ninth review round; the rev-9 record is stale.

## Origin sources read

- #222, #190 §6, the increment-C handoff notes.
- The user's ninth-round findings (validation ordering, coverage evidence
  freshness, admission's in-place mode).
- `scripts/validate-spec.sh:458-484` — the actual admission execution path,
  read to check finding 3 rather than take it on trust.

## Working claim

Scope unchanged since rev 2. Rev 10 orders contract validation before any
producer executes, requires coverage evidence to be freshly produced by a
successful command, and bases the prune on whether a producer will ATTEMPT
isolated-worktree execution.

## Mismatches

- #222's `skip_is_failure` remains deliberately unmet (C3); #222 stays open.

## What rev 10 changed, per finding

1. **Validation ran after producers.** Rev 9's step 3 executed producers and
   step 4 validated the frozen contract, so `resume-unattended-block` could
   run the project's `test.command` before discovering that its policy was
   missing or corrupt — and `resume-attended-block` listed validation as a
   producer and then validated again. Validation is now a PREREQUISITE
   (step 2), `resume-attended-block` has no producer at all, and SC-5g
   asserts a corrupt contract never reaches `test.command`.
2. **Coverage evidence could be stale.** Nothing bound acceptance to a
   successful command or a newly produced artifact, so a previous passing
   report could survive a command that failed without rewriting it — and a
   baseline capture or landing gate would parse it and pass. FR-5a now
   requires: delete the contained artifact, run the frozen command, require
   exit 0, require a newly produced artifact, then parse fail-closed. This
   is the same shape as every "asserted the label, not the thing" defect in
   this arc, which is why it is called out as such in the plan.
3. **Admission does not always create a worktree.** Verified in
   `validate-spec.sh:462-466`: `CCT_ADMISSION_TEST_IN_PLACE=1` opts out
   (a flag I added in #193), non-git projects have no worktrees, and
   `worktree add` can fail. The trigger is now the ATTEMPT at isolated
   execution, and SC-7 asserts the in-place opt-out does not prune.

## Verdict

Verdict: aligned
Confidence: high
