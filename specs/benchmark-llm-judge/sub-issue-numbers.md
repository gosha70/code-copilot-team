# Sub-issue numeric IDs — epic #34 (benchmark-llm-judge)

Filed via `gh issue create --body-file …` on 2026-05-20 per Phase
B0 TB0.4. Every later PR uses the numeric ID column below in its
`Closes #NN` keyword; the placeholder labels A–E never appear in
a PR description. Sub-issue E's closing PR carries a separate
`Closes #34` keyword in addition to `Closes #<E's id>` so the
epic auto-closes when E merges (per memory
`feedback_github_close_keyword_per_issue`: one keyword per real
issue, no shared keyword).

| Label | Numeric ID | Title |
|-------|-----------:|-------|
| A     | #48        | feat(benchmark): Judge protocol + claude_code judge + corpus-selection CLI |
| B     | #49        | feat(benchmark): calibration validation + per-dimension Spearman gate |
| C     | #50        | feat(benchmark): HTML + CSV + static-SVG reports (additive) |
| D     | #51        | feat(benchmark): calibrated-judge winner-extension (deterministic-first enforced) |
| E     | #52        | chore(benchmark): land first labeled calibration set + first calibration-report.md |

Epic: #34 (`feat(benchmark): add calibrated LLM-judge scoring and
rich reports`). Auto-closes via the `Closes #34` keyword in
issue-E's (#52) closing PR.

Dependency graph (informational; enforced by per-PR review, not
automation):

- A (#48) → no prerequisites.
- B (#49) → A (#48).
- C (#50) → no prerequisites; can ship in parallel with A/B.
- D (#51) → A (#48), B (#49), C (#50).
- E (#52) → A (#48), B (#49), C (#50), D (#51). E is the
  human-labeling step; its PR is calendar-gated but does NOT
  block the upstream PRs from merging.

Label set: `enhancement` only (no `benchmark` label exists on
the repo; the standard nine-label set was verified via
`gh label list` 2026-05-20 before filing).

This file is committed alongside sub-issue A's (#48) first
commit in Phase B1; it persists across the cycle so any future
session can identify the sub-issue group without re-querying
GitHub.
