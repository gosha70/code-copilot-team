---
feature_id: auto-build-reviewer-fallback
spec_mode: lightweight
status: approved
date: 2026-09-11
issue: "#190 increment D, part 1 (D1); no child issue by the owner's standing rule"
origin:
  transcripts:
    - specs/auto-build-reviewer-fallback/origin/2026-09-11-owner-request.md
  user_messages:
    - "2026-09-11: 'Can we research/investigate and address Increment D …'"
    - "2026-09-11: 'I would like for DeepSeek to auto review the upcoming D1 work.'"
  documents:
    - "doc_internal/plans/190-increment-d-investigation-2026-09-11.md"
    - "issue #190 §4 (provider_unavailable row), §13"
---

# Spec: reviewer fallback at round time (increment D1)

## Problem

`review-round-runner.sh` consults the subject's `fallback_chain` only
when the configured reviewer fails its healthcheck. A reviewer that
passes the healthcheck (and, since #334, the probe) and then produces no
review on the real request — a broken CLI, a reasoning model with no
content left — ends the round as `provider_unavailable`, and under the
unattended profile ends the run. Three of five real runs ended exactly
there; in run 5 a healthy fallback was configured and never asked.

## User scenarios

- US1: The gating reviewer runs on the round's request and produces no
  review. The same request goes once to the next healthy provider in
  the chain; its verdict gates the round. The ledger says which
  provider failed, why, and which one gated; both invocations are
  debited.
- US2: The gating reviewer answers FAIL. Nothing else is asked: a
  verdict is final; the chain exists for "no review", never for "a
  review I would rather not have".
- US3: The fallback fails too. The round ends as before, exit 3 and
  `provider_unavailable`, with both errors in the detail.

## Requirements

- FR-1: In the runner, when the provider's invocation exits non-zero
  (timeout included), `resolve_fallback_provider(subject, failed)` is
  consulted once: the first provider in the subject's chain that is
  not the subject, not the failed provider, loads and passes its
  healthcheck. The same request file is sent to it with the same
  sandbox environment, its own timeout, and the same verdict parser.
  At most one fallback per round. A zero-exit invocation never falls
  back, whatever its verdict.
- FR-2: The findings file records `reviewer_provider` = the provider
  that answered and, when a fallback happened, `fallback: {from,
  error, invocation_cost_usd}` for the one that failed; the round's
  `cost` state counts both invocations (measured or unmetered each).
  When the fallback fails too, `provider_error.message` carries the
  fallback's error followed by "(after '<from>' failed first: <error>)".
- FR-3: The driver, on a findings file carrying `fallback`, debits the
  failed invocation by the one rule (measured, else the estimate) and
  journals `reviewer_fallback` naming the failed provider, its error
  and the provider that gated the round. The Runs tab lists that event
  among the run's policy decisions.
- FR-4: Tests. Runner: fallback answers (exit 0, both providers named,
  both invocations counted, artifact names the answering one); a FAIL
  from the primary never consults the chain; both fail (exit 3, both
  errors); an unhealthy fallback is skipped and nothing is recorded.
  Driver: an unattended run whose reviewer answers the probe and fails
  the round lands via the fallback with `reviewer_fallback` journaled
  and three estimates debited. Pins updated.

## Constraints

- One PR; no new config key (`fallback_chain` already exists); no
  change to the request format or the verdict parser; the probe (#334)
  is unchanged — it checks readiness, the fallback catches capacity.
- Never "asking models until one says yes": only "no review" triggers
  a fallback, and the ledger names who gated.

## Out of scope

D2 (resume of a terminated run at the review step); adjudication;
builder swap; fallback for advisory panel reviewers.
