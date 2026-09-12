---
feature_id: auto-build-resume-terminated
spec_mode: lightweight
status: approved
date: 2026-09-11
issue: "#190 increment D, part 2 (D2); no child issue by the owner's standing rule"
origin:
  transcripts:
    - specs/auto-build-resume-terminated/origin/2026-09-11-owner-request.md
  user_messages:
    - "2026-09-11: 'Can we research/investigate and address Increment D …'"
  documents:
    - "doc_internal/plans/190-increment-d-investigation-2026-09-11.md"
    - "issue #190 §1 (terminated_policy is terminal in A), §13 (resume arrives with D)"
---

# Spec: resume a terminated run at the review step (increment D2)

## Problem

Under the unattended profile `terminated_policy` refuses `--resume`
outright ("recovery arrives with increment D"). Three of five real runs
terminated at their first review round with a green build commit on the
branch; run 5's recovery — a review-only round over that commit after a
config fix — was done by hand. The attended path already resumes a park
at the review step (`run_phase` sees the phase's build commit and skips
the build). The unattended path should do the same, under conditions
that keep the frozen contract honest.

## User scenarios

- US1: A run terminated `provider_unavailable`; I fix the provider in
  providers.toml (outside the frozen contract) and rerun with
  `--resume`. Admission runs again, the probe included; the review
  step runs again over the same build commit; the run lands or
  terminates again, and the ledger keeps every record of the first
  termination.
- US2: A run terminated on a cap, an accounting failure, a runner error
  or the origin gate; `--resume` refuses with the reason and tells me to
  start a fresh run, as before.
- US3: Someone committed on the branch after the termination;
  `--resume` refuses: the frozen contract no longer describes the head.

## Requirements

- FR-1: `terminated_resumable` allows a resume only when: the
  `disposition_reason` is `provider_unavailable` or `review_breaker`;
  `escalation_resumable(reason, termination.history)` does not refuse
  (a contract that froze no evaluator cannot gain one); the current
  phase has a build commit and it is the branch head; the frozen
  `branch_base_ref` is an ancestor of that head. Otherwise the refusal
  names the reason and exits 1, touching nothing.
- FR-2: A resumable termination proceeds through branch binding,
  prerequisites and preflight as a fresh unattended start does — the
  frozen admission record is reused (the project suite does not run
  again), the reviewer probe runs again — before anything is paid for.
- FR-3: `resume_terminated` moves `termination.json` and
  `triage-report.md` to dated names, sets aside the terminated round's
  review state (journaled `review_state_reset`), reopens the outcome
  (`status: resumed`, `outcome: null`, `disposition_reason: null`) and
  journals `resumed` naming the reason and the kept file. The phase
  then resumes at review through the existing build-commit path; costs
  accumulate across the termination and the resume against the same
  frozen cap.
- FR-4: The triage report says whether the reason is resumable and how,
  or that it has no resume arm.
- FR-5: Tests (driver): terminate at review → fix the provider →
  `--resume` lands with no build session, the outcome re-derived, the
  termination kept under a dated name, the probe run again, costs
  accumulated; a reviewer still broken fails the probe at re-admission
  and terminates again beside the first record; a branch moved past the
  phase's commit refuses; a cap termination refuses and its triage
  report says so. Pins updated.

## Constraints

- One PR; no new config key; no change to the frozen contract's
  identity (#329) or to the attended resume paths.
- Never a resume that replays a build: only the review step runs
  again, over the commit the ledger recorded.

## Out of scope

Resuming a run whose engine changed on master (the branch's checkout
is the engine; a fresh run is right); adjudication; builder swap.
