# 2026-05-06 — User directive: build the origin-confirmation circuit breaker first

This file is the **machine-checkable origin** for the
`origin-confirmation-circuit-breaker` feature. It captures the user's
verbatim directive and the surrounding context that motivated it.

## Verbatim directive

> no, before we start working on Wiki, let implement a "circuit breaker"
> for a builder to auto confirming against orig plan; and if deviation
> is discovered - explicitly asked a user/developer for resolution -
> similar how you ask questions during the planning. This should go
> directly to master; then feat/wiki-ingest-pipeline should be rebased
> on master.

## Context the directive was responding to

Earlier in the same session, the user said (paraphrased; the original
message is preserved in this session's transcript):

- The current implementation of "Wiki" in this repo (PR #27,
  `feat/wiki-ingest-pipeline`) "has nothing to do with what I have
  asked you" — i.e., the LLM Wiki originally specified in
  `specs/llm-wiki-groundwork/spec.md` (issue #12) and described in
  Karpathy's LLM Wiki gist + the linked MindStudio explainers.
- "Not only you confuse and over-use tokens with implementation, but
  you are intentionally derail the clearly defined feature."
- The external review at `~/Downloads/deep-research-report (3).md`
  identifies the deviation precisely: PR #27 is "a guarded page-draft
  generator, not a wiki compiler or maintainer," missing query, lint,
  and existing-wiki awareness during ingest.
- "After this — establish the implementation done in PR #27; and plan
  the correction plan which correlates with my original idea and
  Andrei's LLM Wiki implementation — follow the external review. Put
  the circuit breaker for a future session implementing a new plan to
  always confirm the implementation with the origin !!!"

## What the breaker must do

Distilled from the directive:

1. **Builder-side, automatic.** The check fires inside the build flow,
   not as an after-the-fact audit. Builders auto-confirm before
   delegating.
2. **Origin-comparison.** The check compares the working artifact (the
   `spec.md`/`plan.md`/PR description) against the original plan/idea
   — issue body, external references, transcripts. Not just self-
   consistency of the current spec.
3. **Interactive escalation.** When deviation is discovered, the
   breaker explicitly asks the user/developer for resolution.
   "Similar to how you ask questions during the planning" — the same
   `AskUserQuestion`-shaped prompt used during plan-mode
   clarifications.
4. **Direct to master.** The breaker ships as one PR against `master`,
   not stacked on top of the wiki branch.
5. **Rebase wiki branch onto the new master afterwards.** The wiki
   work resumes only after the breaker is in force, and goes through
   the breaker on day one. The breaker should fire `derailed` on the
   wiki spec the first time it runs there — that is the proof it works
   on real drift.

## Why the breaker is needed (one paragraph)

The PR #27 incident showed that the assistant team can produce work
that satisfies the in-repo derived spec while completely missing the
user's actual ask, and that detection was external. Three roles failed
in sequence: the planner accepted a derived spec as authoritative
without re-checking against the origin; the builder built faithfully
against the derived spec; the reviewer scored implementation quality
of an off-spec artifact and never re-checked alignment. The breaker
adds a structured, machine-checkable origin to every spec, and gates
plan-approval / build-entry / phase-complete on that origin so the same
sequence cannot silently produce a derailed feature again. When it
fires, the user — not the assistant — picks the resolution.
