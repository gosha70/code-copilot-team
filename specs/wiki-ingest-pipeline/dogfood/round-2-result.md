---
doc_kind: experiment-result
target_pr: gosha70/code-copilot-team#27
target_pr_head: d03ac57   # cct head B' read against; preserved post-merge
target_feature_issue: gosha70/rlmkit#37
experiment_kind: A/B comparison — implementation quality with vs. without LLM Wiki
sessions:
  - role: A (no-Wiki control)
    pr: gosha70/rlmkit#38
    branch: feat/llm-wiki-backbone-without-wiki
  - role: B' (with-Wiki, post-rescope)
    pr: gosha70/rlmkit#41
    branch: feat/llm-wiki-backbone-with-wiki-v2
status: published
last_reviewed: 2026-05-07
supersedes: gosha70/rlmkit#39 (Round 1 with-Wiki, ran against pre-rescope cct substrate; not valid evidence for the current PR shape)
---

# PR #27 dogfood — Round 2

This document publishes the Round 2 (post-rescope) dogfood result for
the cct LLM Wiki Maintainer (`gosha70/code-copilot-team#27`). Round 1
is superseded and intentionally omitted from this record because it
measured a different feature shape — the pre-rescope single-source
proposal generator that no longer exists in the merged tree.

## What this is

A small A/B comparison of implementation quality on `gosha70/rlmkit#37`
("Use as backbone for LLM Wiki") run as two parallel autonomous Claude
Code sessions in two git worktrees:

- **Session A** — no Wiki access. Produced rlmkit#38.
- **Session B'** — with read access to cct's rescoped Karpathy-pattern
  Wiki Maintainer at HEAD `d03ac57` (Phase 4 complete + pre-merge
  hardening). Produced rlmkit#41.

Both sessions worked against the same rlmkit start commit and the
same task prompt. The architectural variable that contaminated Round 1
(Session B's sidecar `src/rlmkit/wiki/` package vs Session A's
strategy-registry integration) was held constant in Round 2: B' was
prompted to register as Strategies, same as A.

## What this is not

- **Not strong merge evidence on its own.** The corrected rubric
  scores A = 40 / 45, B' = 41 / 45. A +1-point delta on a 45-point
  bounded rubric with several self-rated dimensions is a noise-level
  signal. The rubric verdict is consistent with "wiki helped a
  little"; it is not a quantitative proof.
- **Not a replacement for live-provider field testing.** Both sessions
  were autonomous Claude Code with `--dangerously-skip-permissions`;
  no curator was present to evaluate the wiki's *workflow* value
  (only its *artifact* value).
- **Not the ground truth on the rubric design itself.** The rubric's
  decision rule (`B − A ≥ 30% × A`) saturates above A = 35/45 and
  was overridden in this run; that override is documented honestly
  below.

## Methodology recap

- rlmkit start commit: `87525d9 ci(security): include ui extra in pip-audit surface` (master).
- Time-box: ~90 min soft / 120 min hard; both sessions stopped at the
  rate-limit boundary, not at task exhaustion.
- Both sessions ran in fresh git worktrees of `gosha70/rlmkit` so the
  baseline tree was identical.
- Session B' had `--add-dir` access to the cct repo at HEAD `d03ac57`,
  giving it read access to:
  - `knowledge/wiki/` (schema, seed pages, index, log)
  - `scripts/wiki_ingest/` (Python package, all four operations)
  - `scripts/wiki` and `scripts/wiki-ingest` (CLI entrypoints)
  - `specs/wiki-ingest-pipeline/spec.md` (design rationale)

## Scorecard

Per the rubric in the experiment plan (kept private at
`doc_internal/pr27-verification-plan.md`).

| # | Dimension | Wt | A — [#38](https://github.com/gosha70/rlmkit/pull/38) | B' — [#41](https://github.com/gosha70/rlmkit/pull/41) | One-line note |
|---|---|---|---|---|---|
| 1 | Wall-clock | 1× | 5 | 4 | A ~50 active min; B' ~60–80 active min after excluding idle/session-pause time. |
| 2 | Design fidelity to A–D | 2× | 4 | 4 | Both cover A–D; A's raw fallback budgeting is naive, B's RLM fallback is scoped to loaded wiki pages. |
| 3 | rlmkit-native integration | 2× | 4 | 5 | B' integrates more idiomatically through first-class strategies, MultiStrategyEvaluator, mode constants, CLI, recursive-controller trace/metadata. |
| 4 | Test count + coverage | 1× | 5 | 4 | A: 19 wiki tests, breadth. B': 10 tests covering forced/skipped wiki_rlm, CLI, lint, promote, full E2E. |
| 5 | Existing tests / lint pass | 1× | 5 | 5 | A: 250 sampled pass. B': 2151 passed, 3 skipped (unchanged). |
| 6 | DESIGN.md quality | 1× | 5 | 5 | Both strong; B' has a more complete borrow/diverge ledger but rubric caps at 5. |
| 7 | Clarifying questions | 1× | 4 | 5 | B' surfaced more operationally useful friction: stale test-count prompt, wall-clock ambiguity, FINAL marker contract, pytest invocation, commit-hook behavior. |
| 8 | Wiki-value evidence (info-only) | 0× | n/a | 5 | Credible schema-borrow AND operations-use evidence: running query/ingest/lint against the cct wiki changed concrete decisions on index-first retrieval, advisory weak-orphan linting, dropping unnecessary legacy compatibility. |

**Weighted totals.** A = 5 + 8 + 8 + 5 + 5 + 5 + 4 = **40**.
B' = 4 + 8 + 10 + 4 + 5 + 5 + 5 = **41**. **B' − A = +1.**

## The threshold was miscalibrated

The original decision rule (`B − A ≥ 0.30 × A`) requires `B' ≥ 52` when
A = 40. The rubric is bounded at 45. The rule is mathematically
impossible to satisfy whenever A scores above ~35, which means it
pre-engineers a "hold" verdict against any well-built no-Wiki baseline
regardless of how much the wiki helped.

This is a calibration error in the rule design, not a signal about
wiki value. Acknowledging it in this published record so the next
dogfood does not repeat it.

A more sensible threshold for a bounded rubric is `B > A AND row 2 ≥ 4`
(positive delta with adequate fidelity), or a fixed-points gap
(`B − A ≥ 3`). Either form would have produced an actionable verdict
for this experiment.

## What this evidence does and does not support

**It does support:**
- The architectural confound from Round 1 was real and removing it
  flipped row 3 (`A=5, B=2`) to (`A=4, B'=5`). Wiki access *can*
  improve idiomatic integration when the architecture variable is
  held constant.
- Row 8's qualitative findings — schema borrow plus operations-use
  changes — describe concrete decisions that would have been more
  expensive without the wiki: index-first retrieval shape, advisory
  weak-orphan linting, dropping legacy compatibility constraints.

**It does not support:**
- A claim that the wiki produces faster first-build times. Row 1
  goes the other way (A 5, B' 4).
- A claim that the wiki produces strictly better artifacts. The +1
  delta is within self-rating noise on a 45-point scale.
- Any merge-as-mandatory framing of the cct PR. The cct PR's merge
  case rests on the spec/origin alignment record, not on this
  dogfood.

## How this experiment relates to the PR #27 merge decision

The cct PR #27 merge case rests on the origin-alignment record at
`specs/wiki-ingest-pipeline/origin-alignment-2026-05-06-2200.md`
(verdict: aligned, high) and the post-rescope code review that
verified spec, code, and tests agree on the Karpathy pattern. This
dogfood is supplementary evidence — it shows the wiki layer is
non-trivially useful to a downstream consumer (rlmkit) — but it is
not the merge case.

## Lessons for the next dogfood

1. **Avoid relative-percentage thresholds on bounded rubrics.** A 30%
   improvement requirement saturates above A ≈ 35/45 and pre-engineers
   the verdict.
2. **Hold confounding variables explicit.** Round 1's architectural
   divergence (sidecar package vs. strategy registry) was an unforced
   confound that distorted row 3 by 3 points; the prompt for Round 2
   pinned this variable.
3. **Pin the substrate version.** Round 1 was invalidated because cct
   PR #27 was rescoped between session start and result review. This
   record pins `target_pr_head: d03ac57` so future readers can
   reproduce against the same code surface.

## Artifacts

- This document.
- Experiment plan (private): `doc_internal/pr27-verification-plan.md`.
- Session A branch (no Wiki): https://github.com/gosha70/rlmkit/pull/38
- Session B' branch (with Wiki, post-rescope): https://github.com/gosha70/rlmkit/pull/41
- cct PR under measurement: https://github.com/gosha70/code-copilot-team/pull/27 at HEAD `d03ac57`.
- Superseded Round 1 with-Wiki branch (do not cite as evidence for
  the current cct PR shape): https://github.com/gosha70/rlmkit/pull/39
