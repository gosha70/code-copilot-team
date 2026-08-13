# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-12 22:00 (amended 23:10, T7 rounds 2-3)
Trigger: T7 review round 1 (P1) — the T6 prune amendment lived only in
tasks.md, contradicting spec.md FR-8/SC-7 and plan.md's lifecycle table
and handoff (4). The amendment is now propagated through all three; the
rev-13 record predates these edits and is stale. Rounds 2-3 narrowed the
in-place exception to SITE scope in the same four documents (FR-8, SC-7,
plan trigger rule + handoff): the override suppresses only the
admission-site prune; coverage-gate worktrees and their prune are
unaffected by it.

## Origin sources read

- #222, #190 §6, the increment-C handoff notes.
- Plan rev 6, finding 3 — the FR-8 "honest trigger": prune immediately
  before THIS RUN creates a throwaway worktree, because the leak it cleans
  up is caused by creating one.
- The T7 reviewer's round-1 findings (P1: tasks.md-only amendment leaves
  T7 internally contradictory; P2s: silent prune failures, missing matrix
  cases, snapshot-setup misclassification).

## Working claim

Scope unchanged since rev 2. T6 (merged PR #236) introduced a SECOND
worktree creator — the coverage gate runs the frozen contract in a
throwaway worktree at each enforcement point, on every coverage-block
path. The FR-8 trigger rule itself is unchanged; the set of creation
sites grew, so the derived per-path table rows grew with it:

- attended greenfield-with-block and resume-attended-block now prune at
  the GATE's creation site (step-3 preflight matrix unchanged);
- attended no-block paths, and in-place admission with no block, still
  never prune — the in-place exception is SITE-scoped (admission only):
  a coverage-block run under it still prunes at the gate (T7 round 2);
- prune failure stays non-fatal and journalled, now including a silent
  nonzero exit (fallback detail naming the code).

This is a derivation update, not a scope change: the normative rule
(honest trigger) is exactly the one the plan has carried since rev 6; the
pre-T6 phrasing "attended greenfield with a block MUST NOT prune" was a
consequence of the old creator set, not an independent requirement.

## Mismatches

- #222's `skip_is_failure` remains deliberately unmet (C3); #222 stays open.

## Verdict

Verdict: aligned
Confidence: high
