---
spec_mode: none
feature_id: contributing-spec-first
risk_category: documentation
justification: |
  Documentation only: a spec-first section and one corrected line in
  CONTRIBUTING.md, one checklist line in the PR template, one prompt in
  the feature-request template, and a CHANGELOG entry. No code, no
  generated artifact, no test count changes.
status: approved
date: 2026-11-14
issue: "#441"
origin:
  issue: "#441"
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/441
  origin_claim: |
    CONTRIBUTING.md never says that a feature needs an approved spec and
    plan before any code is written, nor asks a contributor to agree on an
    approach in the issue first; PR #440 implemented #389 directly as a
    result. Add a short spec-first section in the file's tone linking
    docs/spec-driven-development.md, the spec-workflow and
    origin-confirmation skills and validate-spec.sh; fix the stale
    "README test-count lines" item (the counts live in
    docs/repo-structure.md, pinned against tests/test-counts.env); add a
    linked-issue/approved-plan line to the PR template and a spec_mode
    prompt to the feature-request template.
---

# Plan: CONTRIBUTING.md states the spec-first process (#441)

Documentation only, `spec_mode: none`: this plan is the whole artifact and
the PR review is its approval.

## Changes

1. `CONTRIBUTING.md`: a "Spec-First for Features" section after "How to
   Contribute", 10–15 lines in the file's tone, covering: agree on scope in
   the issue first for anything beyond a bug fix, a docs change or a small
   single-file tweak; features follow SDD with `specs/<feature-id>/` from
   `shared/templates/sdd/` (`plan.md`, plus `spec.md` for `lightweight`,
   plus `tasks.md` for `full`), `status: draft` and the `origin:` block;
   validate with `scripts/validate-spec.sh --feature-id <id>`; the spec PR
   comes first, a maintainer sets `status: approved`, the implementation
   PR follows; an issue that says a specification is required is not open
   for a direct implementation PR. Links: `docs/spec-driven-development.md`
   ("How It Works", "Getting Started with SDD"),
   `shared/skills/spec-workflow/SKILL.md` ("Approval Flow by spec_mode"),
   `shared/skills/origin-confirmation/SKILL.md`.
2. `CONTRIBUTING.md` "Ongoing Alignment Checks" item 2: name
   `docs/repo-structure.md` and `tests/test-counts.env`, which the
   structure suite checks against each other, instead of README lines.
   The strings `tests/test-counts.env` and `.github/workflows/sync-check.yml`
   stay, since `tests/test-shared-structure.sh` greps for them.
3. `.github/pull_request_template.md`: checklist line "Linked issue, and
   for a feature, the approved `specs/<feature-id>/plan.md`".
4. `.github/ISSUE_TEMPLATE/feature_request.md`: a "Specification" prompt
   asking whether the change needs a spec and which `spec_mode`, linking
   `docs/spec-driven-development.md`.
5. `CHANGELOG.md`: one entry under Unreleased → Changed.

## Verification

`validate-spec.sh --feature-id contributing-spec-first`, the origin gate,
`tests/test-shared-structure.sh` after `adapters/claude-code/setup.sh` into
a throwaway HOME (it greps CONTRIBUTING.md), `check-doc-accuracy.sh`,
`git diff --check`, `pre-pr-check.sh --closes 441`.
