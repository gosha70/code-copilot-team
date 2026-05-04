---
page_type: workflow
slug: doc-coverage-audit
title: 30-Day Doc Coverage Audit
status: stable
last_reviewed: 2026-05-03
sources:
  - pr: gosha70/rlmkit#26
  - pr: gosha70/rlmkit#28
  - pr: gosha70/rlmkit#29
---

# 30-Day Doc Coverage Audit

## When to use this

Run this workflow on a recurring basis (~monthly) for any project
where features ship faster than docs follow. Symptoms that the audit
is overdue:

- Long-lived files (`README`, `CLAUDE.md`, `AGENTS.md`,
  `CONTRIBUTING.md`, `.env.example`) reference pre-product
  scaffolding (Neo4j when the real stack is FastAPI; old model IDs
  when current ones are different).
- Several big features shipped in the audit window with zero matching
  user-doc updates.
- New users repeatedly ask "where is the doc for X?" and the answer
  is "in the spec" or "in CHANGELOG."

The reference instance is RLMKit's 2026-04-21 audit covering 232
commits / 4 feature-PRs over 30 days. Audit output: a single-doc
review that produced PRs
[`gosha70/rlmkit#26`](https://github.com/gosha70/rlmkit/pull/26)
(catch-up) and [`#28`](https://github.com/gosha70/rlmkit/pull/28) /
[`#29`](https://github.com/gosha70/rlmkit/pull/29) (archive).

See rlmkit's `doc_internal/reviews/2026-04-21-doc-coverage.md`
(gitignored, available in the rlmkit working tree) for the full
worked example.

## Steps

1. **Fix the window.** Pick a date range (default: 30 days from
   today). Lock it before reading any code so the audit is bounded
   and repeatable.
2. **Inventory what shipped.** `git log --since=<date>
   --pretty=format:'%h %s'` for the window. Group commits by theme
   (e.g., "Learn tab V1→V2", "outcome classifier", "judge rubric").
   Note each theme's representative commits and whether it is
   user-visible.
3. **Inventory what the docs currently say.** For each long-lived
   doc file, note its current claim about the product. For
   `CLAUDE.md` / `AGENTS.md`: what stack is it telling agents to
   work in? For `.env.example`: what model IDs / config keys does
   it list? For the user guide: which surfaces does it cover, and
   which has it omitted?
4. **Cross-reference.** For every theme from step 2, find the doc
   section that should mention it. If none exists or it's stale,
   that's a gap. Three classes of gap to flag separately:
   - **Significant** — entire feature shipped without doc mention.
   - **Minor** — doc mentions feature but with stale details (old
     model IDs, removed flags, old paths).
   - **Drift** — doc references obsolete scaffolding the product
     no longer has (this is the worst kind because it actively
     misleads agents and new contributors).
5. **Cross-reference any uploaded / external docs.** If users or
   collaborators have shared external docs (cookbooks, setup
   notes, runbooks), check whether the repo's canonical doc
   already covers them. Mark each external doc as "superseded,"
   "still adds X/Y/Z," or "stale and should be retired."
6. **Recommend a consolidation, not just patches.** Where the
   information you found scattered across N files belongs in one
   landing doc, write the proposed shape (TOC + 1-line description
   per section). Cite where each piece of content currently lives
   and where it should move.
7. **Rank recommendations by impact-per-effort.** Use a P0 / P1 /
   P2 ranking with rough hour estimates. P0 = ships with the next
   release notes (~2hr each). P1 = ships in the next minor (~half
   day). P2 = nice-to-have (~1hr).
8. **Write the audit as a single markdown doc** under
   `doc_internal/reviews/<date>-doc-coverage.md`. Sections (in
   order): scope + headline summary, what shipped, what the docs
   capture vs. don't, external-doc status, proposed
   consolidation, ranked recommendations, sources.
9. **Open the PRs in priority order.** P0 lands fastest because
   it's smallest. Each PR cites the audit by file path so future
   readers can find the evidence.

## Verification

- Every theme from step 2 has a corresponding line in the
  doc-coverage matrix.
- Every gap classified as "significant" has a concrete remediation
  in the ranked recommendations.
- Every "drift" item has a one-line fix (delete the obsolete
  reference, replace with the current term).
- The next reader of the audit can run the same `git log` window
  and reproduce the inventory.
- The audit cites its own sources at the bottom (commit ranges,
  external docs by path/URL, repo state at audit time).

## Related

- [`spec-driven-development`](../concepts/spec-driven-development.md) —
  the broader convention this audit complements (specs own *what
  shipped*; this audit reconciles that against *what's documented*).
