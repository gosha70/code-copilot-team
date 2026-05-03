---
page_type: playbook
slug: grep-based-acceptance-criteria
title: Grep-Based Acceptance Criteria
status: stable
last_reviewed: 2026-05-03
sources:
  - pr: gosha70/rlmkit#30
  - pr: gosha70/rlmkit#31
  - pr: gosha70/rlmkit#32
  - pr: gosha70/rlmkit#33
---

# Grep-Based Acceptance Criteria

## Symptom

You have a spec section that lists "all" the call sites, files, or
functions that need a particular change. The spec was correct when
written. Then code drifts — a new caller is added, a refactor renames
a symbol, a feature path is split into two — and the enumerated list
goes stale. Implementers following the list literally will leave one
or more sites untouched. Bugs ship.

The triggering instance: round 7 of the RLMKit prefill/decode-telemetry
spec found that §3's list of `run_rlm.py` assistant/execution append
sites ended at line `:1456` and missed the synthesis-fallback
`synth_entry` append at `run_rlm.py:1554`. Implementers following the
list literally would have shipped the feature with one fallback
branch silently dropping the new telemetry keys (TTFT, decode tok/s,
prompt-cache hit rate). The fallback path runs in real production
flows; the gap was not theoretical.

See rlmkit's `doc_internal/specs/prefill-decode-telemetry.md`
(gitignored, available in the rlmkit working tree) for the full
v1.7 preamble describing the gap and the prescription. Public
artifact: [`gosha70/rlmkit#30`](https://github.com/gosha70/rlmkit/pull/30)
and the phase PRs `#31`, `#32`, `#33`.

## Recovery steps

When you discover a stale enumerated list mid-review (or worse,
post-merge):

1. **For every enumerated-list AC in your spec, ask whether it
   could be expressed as a `git grep` predicate over a stable
   identifier.** Stable identifiers include constant names,
   decorators, role markers, type annotations, and well-named
   helper calls. Line numbers are *never* stable identifiers.
2. **Replace the list with the grep + a sample of expected hits.**
   Format:
   > Authoritative AC: `git grep -nE 'TRACE_KEY_ROLE:\s*"assistant"'
   > src/rlmkit/application/use_cases/`. At the time of writing this
   > spec, the grep matches the following lines (illustrative, not
   > exhaustive): `run_rlm.py:1124`, `run_rlm.py:1456`,
   > `run_rlm.py:1554`, `run_direct.py:312`. **The grep is the
   > authoritative AC; line numbers are illustrative.**
3. **Where the grep cannot be made authoritative** (the predicate
   matches too broadly), invert: assert that *every* grep match
   satisfies the new contract, and call out exclusions explicitly.
   Example: "every match must populate the four telemetry keys
   except matches inside `tests/fixtures/` (legacy fixture data,
   tracked in #N)."
4. **Re-run the grep before each review round.** If new matches
   have appeared since the prior round, classify each (in scope
   for this spec, exclude with reason, or update the spec). New
   matches without classification are a stop-and-fix signal.
5. **Land the grep itself in the spec, not just its output.**
   Implementers should be able to copy-paste the grep and
   reproduce the list. A spec that hides the predicate behind
   prose loses the self-checking property.

## Verification

The prescription is working if:

- A subsequent round of review introduces a new call site (or a
  refactor renames a function) and the existing AC catches it
  without spec edits.
- An implementer can produce the current authoritative list by
  running the grep, with no further interpretation.
- A reviewer can sanity-check completeness by re-running the same
  grep and comparing match counts to the count documented when
  the spec was written.
- Post-merge, the same grep run against the merged code shows the
  expected match count and every match satisfies the contract.

The prescription is *not* working if:

- The grep predicate became too broad or too narrow over time and
  the spec author silently fell back to maintaining a parallel
  list.
- A reviewer rejects the grep "for clarity" and asks for line
  numbers in the spec body. (Line numbers in *prose* are fine as
  illustration; line numbers as the authoritative AC are the
  failure mode you are trying to prevent.)
- New matches appear between rounds and no one classified them.

## Prevention

Before writing any AC that enumerates call sites, files, branches,
or fields, run this check:

1. **Is there a stable identifier I can grep for?** If yes, prefer
   the grep.
2. **If no, why not?** Common reasons: the change is nominally
   structural (new method on a class), the predicate is "every
   site that does X *and* Y," or the targets are scattered across
   distinct identifier kinds. In those cases, write the spec
   such that the *implementer's* job is to produce the grep, and
   make their final grep + match count part of the AC.
3. **Never write `at lines X, Y, Z` as the authoritative AC.**
   Line numbers can appear in spec body as illustration ("at the
   time of writing, the matches are at the following lines"), but
   never as the contract.
4. **Encode this discipline in the build prompt.** The RLMKit
   build prompt for this feature explicitly tells the implementer
   to re-grep at the start of each phase rather than trust the
   enumeration. That habit transfers to any multi-PR feature.

## Why this works

Enumerated lists assume code is static between spec-write and
spec-implementation. It isn't. A grep predicate over a stable
identifier survives re-numbering, splits, and refactors as long as
the *identifier* survives. The cost is one round of converting
prose to grep; the savings is unbounded — every future round, every
future contributor, every future refactor.

This is a special case of the broader pattern that
[`spec-code-coherence-drift`](../incidents/spec-code-coherence-drift.md)
documents: specs drift from code unless re-grounded against it
every round. Greps re-ground automatically; enumerated lists do
not.

## Related

- [`spec-code-coherence-drift`](../incidents/spec-code-coherence-drift.md) —
  the incident class this prescription addresses.
- [`multi-round-spec-review`](../concepts/multi-round-spec-review.md) —
  the broader concept this playbook fits inside.
- [`spec-driven-development`](../concepts/spec-driven-development.md) —
  the SDD context.
