---
page_type: concept
slug: multi-round-spec-review
title: Multi-Round Spec Review
status: stable
last_reviewed: 2026-05-03
sources:
  - pr: gosha70/rlmkit#30
  - pr: gosha70/rlmkit#31
  - pr: gosha70/rlmkit#32
  - pr: gosha70/rlmkit#33
---

# Multi-Round Spec Review

## Summary

A spec for a substantial feature can — and often should — go through
multiple review rounds before code lands. Each round catches a
structurally distinct **class** of bug, not just minor edits. The
RLMKit prefill/decode-telemetry feature shipped via four PRs
([`gosha70/rlmkit#30`](https://github.com/gosha70/rlmkit/pull/30) +
phase PRs `#31`, `#32`, `#33`) on the back of a spec that evolved
from v1.0 to v1.7 across seven review rounds. Every round paid for
itself: each version's preamble narrates a defect that would have
shipped if the prior version had been implemented as written.

See rlmkit's `doc_internal/specs/prefill-decode-telemetry.md`
(gitignored, available in the rlmkit working tree) — the v1.7 spec
whose version history is the primary evidence for this concept.

## Key ideas

- **Each round catches a different class of bug.** The seven rounds
  caught wrong-fallback paths, layer-confusion in pseudocode,
  wrong field names at the raw-DTO layer, and incomplete enumerated
  call-site lists. None of these were "minor edits" — each would
  have produced a real defect in shipped code.
- **The cost of rounds is paid by the saved rework.** Each round
  is cheaper than landing the bug, hitting it in production, and
  re-cutting a release. Stop when rounds stop catching new
  *classes* — not when no edits are proposed.
- **Make versions explicit and narrate the diff.** The v1.7 spec's
  preamble walks each prior version (v1.4, v1.5, v1.6) and explains
  what bug class that round caught. A future implementer (human or
  agent) can read the version history as a working post-mortem of
  the spec itself, not just the feature.
- **Re-ground against actual code every round.** The recurring
  failure mode is spec-vs-code drift; every round needs a re-grep
  pass over the affected files. See
  [`spec-code-coherence-drift`](../incidents/spec-code-coherence-drift.md)
  for concrete instances.
- **One mechanic that survives all rounds: prefer self-checking
  predicates over enumerated lists.** Round 7's prescription was
  to swap "list every call site" for "`git grep` for every
  TRACE_KEY_ROLE: 'assistant' append in this directory." That
  prescription is the playbook at
  [`grep-based-acceptance-criteria`](../playbooks/grep-based-acceptance-criteria.md).

## Where this shows up

- **RLMKit prefill/decode-telemetry rollout.** Spec at
  `rlmkit doc_internal/specs/prefill-decode-telemetry.md` (v1 → v1.7,
  ~2000 lines). Public artifacts: the merge PR
  [`gosha70/rlmkit#30`](https://github.com/gosha70/rlmkit/pull/30)
  and the phase PRs `#31` (data model + cache extraction + RAG trace),
  `#32` (use-case trace writers + REST/replay shape), `#33`
  (PREFILL_TIMEOUT classifier + write-time persistence).
- **The corresponding build prompt.** RLMKit's
  `doc_internal/prompts/build-prefill-decode-telemetry.md` (also
  gitignored) tells implementers explicitly: "the spec went through
  seven review rounds; every paragraph is load-bearing." That
  framing is itself a transferred lesson and may become its own
  concept page in a later promotion round.
- **Code-copilot-team's own SDD pattern** (`specs/<feature-id>/`)
  is currently single-pass per feature. Adopting a multi-round
  variant for substantial features would be a low-cost extension.

## Related

- [`spec-code-coherence-drift`](../incidents/spec-code-coherence-drift.md) —
  three concrete drift instances caught across three rounds; the
  evidence layer for this concept.
- [`grep-based-acceptance-criteria`](../playbooks/grep-based-acceptance-criteria.md) —
  the v1.7 prescription that emerged from the rounds.
- [`spec-driven-development`](spec-driven-development.md) — the
  broader SDD context this concept extends.
