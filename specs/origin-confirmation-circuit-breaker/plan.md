---
feature_id: origin-confirmation-circuit-breaker
spec_mode: full
status: draft
origin:
  issue: gosha70/code-copilot-team#0
  transcripts:
    - specs/origin-confirmation-circuit-breaker/origin/2026-05-06-user-directive.md
  origin_claim: |
    "Before we start working on Wiki, let implement a 'circuit breaker' for a
    builder to auto confirming against orig plan; and if deviation is
    discovered - explicitly asked a user/developer for resolution - similar
    how you ask questions during the planning. This should go directly to
    master; then feat/wiki-ingest-pipeline should be rebased on master."
    The breaker exists because PR #27 (wiki-ingest-pipeline) shipped a
    "guarded page-draft generator" while the user's actual origin (issue #12 +
    Karpathy's LLM Wiki gist) called for a wiki maintainer with three
    operations (ingest-updates-existing-wiki / query / knowledge-health lint).
    Detection of that scope mismatch came from a third-party external review,
    not a self-check. The breaker makes the same failure architecturally
    impossible to repeat by gating plan-approval, build-entry, and
    phase-complete on a structured origin-alignment check, escalating
    interactively to the user on deviation.
---

# Plan — Origin-Confirmation Circuit Breaker

## Approach

Build the breaker as four cooperating pieces, all propagated through the
existing `shared/skills/` → `scripts/generate.sh` machinery so every adapter
(Claude Code, Codex, Cursor, GitHub Copilot, Windsurf, Aider) picks it up
automatically:

1. **Frontmatter convention** — every `specs/<id>/plan.md` carries an
   `origin:` block. `scripts/validate-spec.sh` enforces it.
2. **Skill** — `shared/skills/origin-confirmation/SKILL.md`, added to the
   `ALWAYS_SKILLS` list at `scripts/generate.sh:18`. Defines the
   alignment-check protocol, the three gates, and the interactive
   escalation contract.
3. **Verifier script** — `scripts/check-origin-alignment.sh <feature-id>`,
   bash 3.2 + awk, mirrors `knowledge/wiki/scripts/lint-wiki.sh` style.
   Six exit codes, one per outcome.
4. **Wire-through** — three existing skills (`spec-workflow`,
   `phase-workflow`, `agent-team-protocol`) gain explicit hooks that call
   the script and surface the escalation. One bullet added to
   `claude_code/.claude/rules/coding-standards.md`. One new slash command
   `/origin-check`.

Self-dogfood from day one: this very plan satisfies the breaker against its
own origin (the user's directive, captured as a transcript in the `origin/`
sibling directory).

## Files to create

- `specs/origin-confirmation-circuit-breaker/spec.md`
- `specs/origin-confirmation-circuit-breaker/tasks.md`
- `specs/origin-confirmation-circuit-breaker/origin/2026-05-06-user-directive.md`
  (verbatim quote of the user's directive — the machine-checkable origin)
- `shared/skills/origin-confirmation/SKILL.md`
- `scripts/check-origin-alignment.sh`
- `claude_code/.claude/commands/origin-check.md`
- `adapters/claude-code/.claude/commands/origin-check.md`
- `tests/test-origin-alignment.sh`
- `knowledge/wiki/workflows/origin-alignment.md` (workflow page, page_type
  `workflow`, must lint clean)
- `knowledge/wiki/IMPLEMENTATION_STATUS.md` (feature × status table — also
  records the backfill exit codes so the pre-existing PR #27 scope mismatch
  is visible)

## Files to modify

- `scripts/generate.sh` — add `origin-confirmation` to the
  `ALWAYS_SKILLS` list at line 18.
- `scripts/validate-spec.sh` — extract origin frontmatter; reject specs
  missing it (with `origin: { type: internal | unrecoverable }` escape
  hatches).
- `shared/skills/spec-workflow/SKILL.md` — declare `origin:` as a required
  plan.md frontmatter key.
- `shared/skills/phase-workflow/SKILL.md` — add an "Origin alignment gate"
  step before peer review in the post-phase checklist.
- `shared/skills/agent-team-protocol/SKILL.md` — directive that the build
  agent runs `check-origin-alignment.sh` as its first action and refuses
  to delegate on exit ≥ 2.
- `claude_code/.claude/rules/coding-standards.md` — one bullet under
  "Verification Discipline".
- `adapters/claude-code/.claude/commands/phase-complete.md` — call the
  alignment script after step 1, abort on exit ≥ 2.
- `tests/test-shared-structure.sh` — add `origin-confirmation` to the
  `SKILL_NAMES` array at line 118; bump `exactly 20 skills` → `21` at line
  148; bump `README lists 20 skills` → `21` at line 832.
- `tests/test-generate.sh` — extend the always-skill case statements at
  lines 115 and 342; bump `exactly 20 .mdc files` → `21` at line 263; add
  `origin-confirmation` to the always-skill verification loop around line
  268.
- `tests/test-counts.env` — recalibrate `TEST_GENERATE_EXPECTED_PASS` and
  `TEST_SHARED_STRUCTURE_EXPECTED_PASS` after running once and counting
  the delta.
- `README.md` — bump skill counts to match.
- `knowledge/README.md` — add "Origin alignment" section.
- `CLAUDE.md` (root) and `claude_code/.claude/CLAUDE.md` — one-line
  directive pointing at the script and skill.
- All seven existing `specs/*/plan.md` files — backfill `origin:`
  frontmatter (or `origin: { type: internal }` for genuinely-internal
  specs). The backfill on `wiki-ingest-pipeline` deliberately surfaces
  the pre-existing scope mismatch.

## Test strategy

- `tests/test-origin-alignment.sh` covers all six exit codes of the
  verifier script and the rendering of the escalation block.
- `tests/test-shared-structure.sh` and `tests/test-generate.sh` continue
  to pass with bumped counts.
- `scripts/validate-spec.sh --all` continues to pass after the backfill.
- `bash knowledge/wiki/scripts/lint-wiki.sh` continues to exit 0 (the new
  `workflows/origin-alignment.md` page lints clean).
- **Self-dogfood:** `scripts/check-origin-alignment.sh
  origin-confirmation-circuit-breaker` returns exit 0 (`aligned, high`).
- **Adapter propagation:** after `scripts/generate.sh`, the
  `origin-confirmation` skill body appears in:
  - `adapters/codex/AGENTS.md`
  - `adapters/cursor/.cursor/rules/origin-confirmation.mdc` with
    `alwaysApply: true`
  - `adapters/github-copilot/.github/copilot-instructions.md`
  - `adapters/windsurf/.windsurf/rules/rules.md`
  - `adapters/aider/CONVENTIONS.md`
- **Manual interactive check:** deliberately produce a `partial` verdict
  on a fixture spec; confirm the slash command surfaces the three
  resolutions (A/B/C) via `AskUserQuestion`-shape, with no fourth option.

## Delegation

This is a single-session build. No sub-agent delegation needed — the work
is sequential (spec → script → skill → wiring → tests → backfill → docs)
and each step depends on the previous.

## Rollout

One PR against `master`, titled
`feat: origin-confirmation circuit breaker (auto-detect spec/origin drift, escalate to user on deviation)`.

After merge:

1. `git fetch origin master`.
2. On `feat/wiki-ingest-pipeline`: `git rebase origin/master`.
3. Run `scripts/check-origin-alignment.sh wiki-ingest-pipeline` — expected
   verdict: `derailed` (the breaker fires on the very mismatch that
   motivated it). The user picks A/B/C in the next session.

Wiki work itself is **out of scope for this plan**. It resumes after
rebase, in a fresh planning session, gated by the now-active breaker.
