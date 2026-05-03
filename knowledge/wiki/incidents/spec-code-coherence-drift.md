---
page_type: incident
slug: spec-code-coherence-drift
title: Spec/Code Coherence Drift — Three Instances Across Three Review Rounds
status: stable
last_reviewed: 2026-05-03
sources:
  - pr: gosha70/rlmkit#30
  - pr: gosha70/rlmkit#31
  - pr: gosha70/rlmkit#32
  - pr: gosha70/rlmkit#33
---

# Spec/Code Coherence Drift — Three Instances Across Three Review Rounds

## What happened

Across three consecutive review rounds (v1.4 → v1.5 → v1.6) of the
RLMKit prefill/decode-telemetry spec, three structurally distinct
kinds of spec/code drift were caught. Each was a real defect: had
the spec been implemented as written at that round, real call sites
or assertions would have been wrong in the shipped code. The
reviewer caught them only by re-grounding the spec against actual
source on every round — not by re-reading the prose.

The class is "the spec asserts on code structure that doesn't
match the code." The three instances differ in *mechanism* (wrong
branch, wrong layer, wrong field name) but share that root cause.

See rlmkit's `doc_internal/specs/prefill-decode-telemetry.md`
(gitignored, available in the rlmkit working tree) — the v1.7
spec preamble narrates each round's diff and is the primary
evidence for this incident page. The public artifacts that landed
the corrected spec are
[`gosha70/rlmkit#30`](https://github.com/gosha70/rlmkit/pull/30)
and the phase PRs `#31`, `#32`, `#33`.

## Why it happened

Spec prose drifts from code as soon as either changes without the
other being re-grounded. There is no automatic check that "the
sentence I wrote about line 1456 still describes what's at line
1456." Three sub-mechanisms surfaced in this rollout:

1. **Pseudocode written in the wrong layer's vocabulary.** The
   reviewer described a domain-object operation when the actual
   code at that layer manipulates raw DTO dicts. Layer boundaries
   are easy to confuse in spec prose because the *concepts* (a
   "trace step") survive the boundary; only the *types* don't.
2. **Field names borrowed from the materialized layer when the
   raw layer uses different keys.** Same root cause — a
   pre-canonical layer often uses raw constant names that the
   spec author has internalized as the "real" name from the
   downstream layer.
3. **A fallback path that the spec omitted.** Specs tend to
   describe the *primary* code path; fallback / synthesis /
   error branches get lost. If the spec is the authoritative
   contract, the omission ships.

## Instances

### Round v1.4 → v1.5 — Wrong fallback branch

v1.4's prose for `_translate_raw_trace_entry` claimed the
canonicalizer "promotes to `error` when `is_last + !run_success`."
That is not what `src/rlmkit/server/routes/chat.py::_canonical_action_type`
actually does — it maps `assistant → inspect`, `execution → subcall`,
and promotes the last step to `final` **only** when
`success=True`. Failed-terminal steps keep their role-mapped
`action_type` (usually `inspect`); there is no `error` branch.

If implemented as v1.4 specified, the codebase would have grown a
phantom `error` branch (or developers would have spent time
looking for one that isn't there). v1.5 deleted the phantom branch
from the spec and noted that the classifier keys on TTFT/duration
ratios, not on `action_type`, so no wrapper is needed.

### Round v1.5 → v1.6 — Layer confusion (`TraceStep` vs raw dict)

v1.4/v1.5 §3 ("Use-case integration") still showed
`step = TraceStep(...)` pseudocode as if the use cases emit domain
objects. They do not — `RunResultDTO.trace` is
`list[dict[str, Any]]`, and `run_rlm.py` / `run_direct.py` append
raw DTO dicts keyed by `TRACE_KEY_*` constants. `TraceStep` is
reserved for the post-materialization view that the route layer
produces via `_translate_raw_trace_entry`.

Following v1.5's pseudocode literally would have produced
`TraceStep` objects in the use-case layer, breaking the layer
contract and the downstream materialization step. v1.6 rewrote §3
in raw-DTO terms: use cases **append serialized trace dicts**;
`TraceStep` only appears at the route boundary.

### Round v1.6 → v1.7 — Wrong field names at the raw-DTO layer

AC-13a still referenced *materialized* token field names —
`prompt_tokens` / `completion_tokens` — at the raw-DTO layer
where they don't exist. The raw keys are `TRACE_KEY_INPUT_TOKENS` /
`TRACE_KEY_OUTPUT_TOKENS` (literal values `"input_tokens"` /
`"output_tokens"`).

A test written from v1.6's AC-13a would have asserted on
`step["prompt_tokens"]`, found `None`, and either reported a
false failure or — worse — passed because `None != expected`
already failed for unrelated reasons. v1.7 corrected the AC to
match the actual test snippet keys.

## What we changed

- **A fourth round (v1.7)** that did one final re-grounding pass
  and produced a generic prescription: replace enumerated
  call-site lists with `git grep` predicates over stable
  identifiers. That prescription is the playbook at
  [`grep-based-acceptance-criteria`](../playbooks/grep-based-acceptance-criteria.md).
- **Explicit version-bumps with narrated diffs.** Each version
  preamble in the spec now describes which class of drift the
  prior version contained. Future readers (human or agent)
  can read the version history as a working post-mortem of the
  spec.
- **Phase-by-phase build PRs** (`gosha70/rlmkit#31`, `#32`, `#33`)
  rather than a single landing PR — limits the blast radius if a
  drift slipped through one round.

## How to recognize a recurrence

Symptoms in spec prose that should trigger a re-grounding pass:

- **Pseudocode that names types without checking the actual
  signatures.** If the spec says `step = TraceStep(...)` or
  similar, grep the codebase for the constructor and confirm it
  is callable from the layer the spec describes.
- **Field-name strings that "feel right" but came from a
  different layer.** If the spec asserts `result["prompt_tokens"]`
  in a layer that uses constants like `TRACE_KEY_*`, suspect
  drift.
- **Branch enumerations claiming "all" or "every" without a
  predicate.** "All assistant-role appends are at lines X, Y, Z"
  is a brittle assertion; "every line matching `TRACE_KEY_ROLE:
  \"assistant\"` under `application/use_cases/`" is a self-checking
  one. See the playbook.
- **Spec prose that reads as if the writer remembered the code
  rather than re-read it.** When a reviewer can write the diff
  from memory, drift is already there.

The single most reliable detector is the discipline itself: every
review round re-greps the affected files instead of re-reading
the prior version's prose.
