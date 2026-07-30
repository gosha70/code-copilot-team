# Tasks: Copilot Reviewer Setup

Task IDs: `R<n>`. All tasks delivered across PR #148 and the follow-up
remediation PR (see plan.md §Pull-request decomposition).

- [x] **R1 (P0)** `shared/review/CODE_REVIEW.md` — full independent-review
  workflow (FR-7); Project Configuration section delegates to the
  project-owned file.
- [x] **R2 (P0)** `shared/review/reviewer-loader.md` — loader section
  directing sessions to the review + project-config documents.
- [x] **R3 (P0)** `shared/review/project-config-template.md` —
  project-owned configuration template (FR-3).
- [x] **R4 (P0)** `scripts/setup-reviewer.sh` — abstracted installer:
  dispatch table, marker-guarded upsert, ownership rules, foreign-file
  refusal, generated-file handling, uninstall (FR-1..FR-5).
- [x] **R5 (P0)** `scripts/generate.sh` loader-block emission into
  `adapters/codex/AGENTS.md` within the size cap (FR-6).
- [x] **R6 (P0)** `tests/test-setup-reviewer.sh` — FR-mapped suite
  including the review-found regressions: project-config survival across
  refresh/uninstall; stale generated `AGENTS.md` exits 65 with the
  regeneration command (FR-8, C-2).
- [x] **R7 (P1)** README: reviewer-setup section + repo-structure entries.
- [x] **R8 (P1)** SDD bundle (this directory) with origin metadata and the
  Phase 4.2 relationship recorded.
