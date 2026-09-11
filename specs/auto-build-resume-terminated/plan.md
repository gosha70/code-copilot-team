---
spec_mode: lightweight
feature_id: auto-build-resume-terminated
risk_category: infra
justification: |
  Two functions in the driver's resume dispatch reusing the existing
  attended park-resume machinery (escalation_resumable, the
  build-commit resume in run_phase, the review-state set-aside), plus
  wording in the triage report. FR-1..FR-5 in spec.md state the
  behaviour.
status: approved
date: 2026-09-11
issue: "#190 D2"
origin:
  transcripts:
    - specs/auto-build-resume-terminated/origin/2026-09-11-owner-request.md
  user_messages:
    - "2026-09-11: 'Can we research/investigate and address Increment D …'"
  origin_claim: |
    Let a terminated unattended run resume at the review step when the
    fix was outside the frozen contract and the build commit is still
    the branch head, with admission (probe included) run again first.
    Scoped from run 5's hand-run recovery; not a build replay, not
    adjudication, not a builder swap.
---

# Plan: resume a terminated run at the review step (D2)

## Deliverables

1. `scripts/auto-build-loop.sh`: `terminated_resumable`,
   `resume_terminated`; the step-0 short-circuit lets a resumable
   termination re-admit; the step-7 dispatch calls `resume_terminated`;
   the triage report names the resume arm (FR-1..FR-4).
2. Tests in `tests/test-auto-build-loop.sh`; pins (FR-5).
3. README paragraph.

## Test strategy

Mock reviewer that answers the probe and fails the round (terminates),
then a passing profile on `--resume`; a still-broken profile; a hand
commit on the branch; a cap termination via a $13 build session.
