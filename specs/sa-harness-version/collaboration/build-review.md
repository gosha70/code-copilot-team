---
feature_id: sa-harness-version
date: 2026-09-24
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feat/371-a4b-harness-compare
rounds_completed: 2
attempt_count: 1
bypass: false
---

# Peer Review: sa-harness-version — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 2
**Verdict**: PASS

## Summary

The A4b harness-compare build is well-structured and the four P1/P2 issues from the owner's review (mixed-first precedence, cross-dialect boolean predicate, turn-weighted rates, kind/value separation) are correctly fixed and pinned by tests. The remaining findings are minor: a few implicit invariants, one test that reads source text rather than exercising behavior, and some documentation gaps. No blocking issues.

## Findings

- [note] f-47cc9d5e: The Round-1 concern about coupling to a private symbol is real, but the builder's resolution is sound: `test_the_median_is_the_package_s_one_percentile_rule` asserts the two agree, so a rename or signature change fails loudly rather than drifting. Acceptable as-is; a public re-export would be marginally cleaner. (scripts/session_analytics/api/dashboard.py)
- [note] f-e795ae76: The `NOT (a IS NULL AND b IS NULL ...)` form is correct on both dialects and the partition test proves it over all five dimensions. The Round-1 fragility note stands only if `HARNESS_FACTS` ever gains a nullable-by-design column; today it is a closed set of stamp facts. (scripts/session_analytics/mcp/tools.py)
- [note] f-e9cac879: The gate reads `harnessView.ts` as text and regex-matches `GROUP_*` declarations. This catches drift in the literal values but not in usage (e.g. a component that hardcodes `"mixed"` instead of `GROUP_MIXED`). It is a reasonable cheap gate; note the limitation. (scripts/session_analytics/tests/test_harness_compare.py)
- [note] f-4a646d43: The rename from `TestPostgresDialect` is honest and the docstring says what it does. The test still only greps generated SQL; a real Postgres run remains the integration suite's job, as stated. (scripts/session_analytics/tests/test_harness_compare.py)
- [note] f-72a98188: The `str()` coercion is safe today because the CASE guarantees `_KIND_VALUE` only when `s.{by} IS NOT NULL`. The implicit invariant is documented in the comment above `kind_sql`; acceptable. (scripts/session_analytics/api/dashboard.py)
- [note] f-29baa2e2: The README now lists all four filter forms in prose, addressing the Round-1 finding. The row table and the prose agree. (scripts/session_analytics/README.md)
- [note] f-143a7d3d: The function is dense but the three sub-queries are separate statements with their own comments, and the builder's argument that splitting them would add indirection without a testable seam is reasonable. The partition test exercises the whole path. (scripts/session_analytics/api/dashboard.py)
- [note] f-af1376e5: `keep_clause` is built for the session alias and used identically in both queries; the Round-1 concern about turn-column predicates is not applicable because `keep_clause` is session-only by construction. The `priceable_turns` semantics (model present, cost may be NULL) match the documented pricing contract. (scripts/session_analytics/api/dashboard.py)
- [note] f-f587e355: The absent branch correctly requires `wanted IS NULL AND NOT (no_facts) AND NOT mixed`, matching the aggregate's CASE order. The facet query excludes mixed and NULL, so offered values round-trip. Consistent. (scripts/session_analytics/mcp/tools.py)
- [note] f-506b9902: The test mutates the store mid-test (adds `s-empty`, deletes `s-b`/`s-b2`) and re-queries. The builder notes each test gets a fresh store from `setUp`, so cross-test contamination is not a concern; within-test ordering is intentional. (scripts/session_analytics/tests/test_harness_compare.py)
- [note] f-e665007c: The origin file records the owner's review and the four adopted fixes with reproduction notes. This is good provenance; the alignment records at 2330 and 0100 are consistent with the code. (specs/sa-harness-version/origin/2026-09-24-owner-direction.md)
