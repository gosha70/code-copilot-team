---
spec_mode: lightweight
feature_id: review-provider-error
risk_category: feature
justification: |
  Bug fix (#204) that changes a contract: the review runner gains exit
  code 3, and the driver gains a park arm for it. Escalated from `none`
  per the spec-workflow "when in doubt" rule because it alters gate
  behaviour (what a failed reviewer does to a run) and spend accounting.
status: approved
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/204
  origin_claim: |
    Bug #204: "Reviewer CLI failure is reported as review FAIL — triggers
    fix sessions on zero findings, burns rounds, parks as misleading
    git_anomaly". When the reviewer CLI itself fails to run (non-zero
    exit, no review performed), review-round-runner.sh reports a normal
    code-review FAIL. The driver treats it as real feedback: spawns fix
    sessions against ZERO findings, makes unplanned commits, burns review
    rounds and money, and parks with a misleading git_anomaly that names
    nothing about the actual cause. Observed: 2 wasted review rounds +
    2 fix sessions, 1 unplanned commit, ~$4 of a $6.76 run — because
    codex exited non-zero with a one-line usage error.
---

# Plan: a broken reviewer is not a verdict (#204)

`REVIEW_EXIT` is the provider *process* exit code. Non-zero means the
reviewer never ran, which is infrastructure, not a judgement about the
code — but it was mapped onto `FAIL`, the same vocabulary as a genuine
rejection, so the driver could not tell "reviewer is broken" from "your
code has problems".

## Changes

1. **Runner**: a non-zero provider exit yields `INCONCLUSIVE` (fail-closed,
   never a pass), records `provider_error: {exit_code, message}` in
   `findings-round-N.json`, and exits **3**. The provider *timeout* path
   (124/143) previously exited 1 and is the same class — it now exits 3
   too. A genuine review that fails the code still exits 1.
2. **Driver**: a new `rc=3` arm parks as `provider_unavailable` — an
   existing, accurate park reason — naming the provider, its exit code,
   and its first line of output. No fix session, no burned round.
3. **Spend**: `rc=3` debits anything the adapter genuinely MEASURED but
   never falls back to the conservative estimate. The observed run
   charged `$2.0 (estimated: true)` for a reviewer that exited on a usage
   error; a failed invocation is not an unmetered one.

## Constraint

The reviewer's own text is still not a measurement or a verdict channel
(#193, #200). This adds a process-level signal — the provider's exit
code, which the model cannot forge — and nothing else.

## Relationship to #205

The run that produced this report also produced #205 (the review-loop
wall-clock counting parked time). #205's `git_anomaly` park was this
bug's downstream symptom, so this lands first. #205 remains open.
