# Origin alignment check — sa-harness-version (A4b, after review)

Checked 2026-09-25 01:00, after the owner's review of the A4b build and
the fixes for it. Supersedes the 2330 record.

Origin: specs/sa-harness-version/origin/2026-09-24-owner-direction.md
(now including the A4b review) and issue #371, row A4.

What the review corrected, and where it stands:

1. The groups PARTITION the store. `mixed` is tested first in the
   aggregate's CASE and excluded from every other group's filter, so a
   session whose earliest stamp carries no facts is mixed and nothing
   else. `harnessState` uses the same precedence. Pinned by a test that,
   for all five dimensions, sums the rows to the session count and
   follows every row's own link, asserting the links cover each session
   exactly once.
2. No boolean-to-integer comparison is generated. One shared predicate,
   `harness_mixed IS NOT TRUE`, valid on both dialects (verified on
   SQLite 3.48). Pinned by a test that greps every generated clause and
   asserts the facet query — which runs on every sessions request —
   uses it.
3. The two rates are weighted by `labeled_turn_count`, as the spec's
   "over labelled turns" requires; `avg_interaction_quality` stays the
   mean of per-session means, as specified. Pinned by the 1-turn vs
   99-turn case: 0.01, not 0.50.
4. A row carries its `kind` separately from the dimension's `value`
   (null for a named group), so a version string that spells "mixed"
   stays a value row with its own link and React key. Pinned in both
   the Python tests and states-check.

Verdict: aligned
Confidence: high
