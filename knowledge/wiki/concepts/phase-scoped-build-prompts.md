---
page_type: concept
slug: phase-scoped-build-prompts
title: Phase-Scoped Build Prompts
status: stable
last_reviewed: 2026-05-03
sources:
  - pr: gosha70/rlmkit#30
  - pr: gosha70/rlmkit#31
  - pr: gosha70/rlmkit#32
  - pr: gosha70/rlmkit#33
---

# Phase-Scoped Build Prompts

## Summary

When a feature spec spans multiple PR-sized phases, scope each agent
build invocation to **one phase at a time**. The build prompt names
the phase, points at the spec, enumerates the read-first / plan-first
discipline, and lists the gotchas the spec covers but are easy to
miss. The agent produces one phase's PR per invocation, not the
whole feature.

The reference instance is RLMKit's
`doc_internal/prompts/build-prefill-decode-telemetry.md` (gitignored,
available in the rlmkit working tree). It paired with a 7-round spec
and shipped via four phase PRs:
[`gosha70/rlmkit#30`](https://github.com/gosha70/rlmkit/pull/30) plus
`#31`, `#32`, `#33`. Each phase landed independently with its own
review.

## Key ideas

- **One phase per invocation.** "Implement the whole feature" is too
  big for any agent to keep coherent across N PRs. The prompt
  explicitly says: "Do not bundle phases. The spec's phasing exists
  so each diff is reviewable."
- **Read-first discipline is non-negotiable.** The first instruction
  is "read the spec in full — every paragraph is load-bearing."
  Agents that skim the spec produce diffs that drift from it. The
  prompt says so out loud.
- **Plan-first before any code.** Before touching code, the agent
  produces a written work plan: every file it will modify, the AC(s)
  each change satisfies, the tests it will add, any open questions.
  The plan goes to a reviewable file (e.g., under `doc_internal/
  plans/`) so the diff is auditable even if no human review is
  available in the loop.
- **Per-phase branch + per-phase PR.** Branch name encodes the
  phase number and a short slug (`feat/<feature>-phase-N-<slug>`).
  The PR description lists the ACs satisfied in that phase, test
  counts, and any spec deviations.
- **Run the full test gauntlet, not the convenient subset.** The
  prompt enumerates every check that must pass before the phase is
  declared done: unit tests, type checker, frontend tests, frontend
  type check. Running only "the tests that touched files in this
  phase" is the failure mode this list prevents.
- **List the gotchas that are easy to miss.** Even a load-bearing
  spec has details that an inattentive read will skip. The prompt
  has a `## Gotchas` section that names them: layer-confusion
  pitfalls, type-protocol breaking changes, migration bootstrap
  rules, completeness greps. These are concrete sentences, not
  general advice.
- **Tell the agent what to do when the spec is wrong.** "If the
  spec contradicts the code, trust the code and call out the
  contradiction in your work plan." This converts spec drift from
  a bug-shipping path into a review signal.

## Where this shows up

- **RLMKit prefill/decode-telemetry rollout.** Six phases, four
  PRs (some phases bundled at the PR level when small), spec at
  `rlmkit doc_internal/specs/prefill-decode-telemetry.md`. Each
  phase invocation used the build prompt at
  `rlmkit doc_internal/prompts/build-prefill-decode-telemetry.md`
  with the phase number swapped in.
- **The gotchas list itself is a methodological export.** It
  encodes lessons from the seven spec review rounds. A future
  agent reading the prompt benefits from rounds it never
  participated in.
- **Code-copilot-team's own SDD pattern** (`specs/<feature-id>/
  tasks.md`) is the closest analog but doesn't yet pair with a
  per-phase build prompt. Adopting one for substantial multi-phase
  features would be a low-cost extension.

## Related

- [`multi-round-spec-review`](multi-round-spec-review.md) — the
  spec-side companion. The build prompt amortizes lessons from
  the spec rounds.
- [`grep-based-acceptance-criteria`](../playbooks/grep-based-acceptance-criteria.md) —
  one of the gotcha-list disciplines this concept depends on
  (the spec's enumerated lists become the prompt's grep
  predicates).
- [`spec-code-coherence-drift`](../incidents/spec-code-coherence-drift.md) —
  the failure class the gotcha list addresses.
- [`spec-driven-development`](spec-driven-development.md) —
  the SDD context.
