# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-09 04:20
Trigger: plan.md, spec.md and tasks.md revised to rev 9 after the user's
eighth review round; the rev-8 record is stale.

## Origin sources read

- #222, #190 §6, the increment-C handoff notes.
- The user's eighth-round findings (sequences vs the emission table; prune
  excluded unattended no-block; unconditional clock override).

## Working claim

Scope unchanged since rev 2. Rev 9 collapses the two literal sequences into
one path-parameterised flow whose table drives producers, file emission,
prune, clock origin and imports — so those five facts are stated once rather
than restated in prose that can drift.

## Mismatches

- #222's `skip_is_failure` remains deliberately unmet (C3); #222 stays open.

## What rev 9 changed, per finding

1. **The literal sequences still described rev 4's world** — `mode: fresh`,
   "import contract + accounting" on every fresh run, admission on every
   resume — which is wrong for four of the seven paths. They are replaced by
   a single sequence parameterised by the computed `PATH`, plus a table with
   a column per decision. Restating per-path facts in prose is what produced
   three consecutive rounds of contradiction findings; deriving them from one
   table removes the failure mode rather than fixing this instance of it.
2. **The prune rule wrongly excluded every no-block run.** An unattended
   no-block path still runs admission, which creates a throwaway worktree —
   and FR-2 already listed that prune as one of its two exceptions, so the
   documents disagreed with each other. The rule is now "prune iff an
   applicable producer creates a worktree", asserted on
   `fresh-unattended-noblock` specifically.
3. **The clock override was unconditional**, so an attended no-block run
   would have started counting preflight/config time it excludes today —
   breaking the byte-identical promise on the very paths that promise
   protects. Clock origin is now per path: `ATTEMPT_START` iff a pre-ledger
   producer runs, else today's `now`. The consequence for attended runs that
   OPT INTO coverage (their initialisation is counted) is stated rather than
   left implicit, and SC-7c asserts the no-block case against the pre-change
   driver.

## Verdict

Verdict: aligned
Confidence: high
