# Tasks — Origin-Confirmation Circuit Breaker

Each task is bounded, independently verifiable, and ordered so the
self-dogfood verdict (`scripts/check-origin-alignment.sh
origin-confirmation-circuit-breaker` → exit 0) can be exercised as soon
as the script and the alignment record exist.

## T1 — Capture origin transcript

- **Output:** `specs/origin-confirmation-circuit-breaker/origin/2026-05-06-user-directive.md`
  containing the verbatim quote of the user's directive plus the prior
  session's PR #27 retraction self-eval.
- **Done when:** the file is committed and `origin_claim` in
  `plan.md`/`spec.md` quotes from it.

## T2 — Build verifier script

- **Output:** `scripts/check-origin-alignment.sh`, executable, bash 3.2
  + awk only.
- **Done when:** all six exit codes (0–5) round-trip on hand-crafted
  fixtures and the script's `--help` documents them.

## T3 — Build origin-confirmation skill

- **Output:** `shared/skills/origin-confirmation/SKILL.md` with proper
  frontmatter (`name`, `description`) matching the existing skill
  shape.
- **Done when:** body defines the alignment-check procedure, the three
  gates, the verdict block format, the three-resolution escalation
  contract, and the rule against silent bypass.

## T4 — Wire into ALWAYS_SKILLS

- **Output:** `scripts/generate.sh:18` updated; running
  `scripts/generate.sh` produces a refreshed adapter set with the new
  skill present in codex AGENTS.md, cursor alwaysApply mdc,
  copilot-instructions.md, windsurf rules.md, aider CONVENTIONS.md.
- **Done when:** `git status adapters/` shows the new skill body in
  each generated artifact and the diff is reviewed.

## T5 — Extend validate-spec.sh

- **Output:** `scripts/validate-spec.sh` rejects any plan.md missing
  `origin:`. Accepts `origin: { type: internal }` and
  `origin: { type: unrecoverable }` as escape hatches with required
  reasons.
- **Done when:** running against a temporary fixture without `origin:`
  exits 1; running against this feature's plan.md passes; running
  against all backfilled specs (after T9) exits 0.

## T6 — Wire phase-complete

- **Output:**
  `adapters/claude-code/.claude/commands/phase-complete.md` calls
  `scripts/check-origin-alignment.sh <feature-id>` after step 1
  (Gather Context). Exit ≥ 2 aborts the command and surfaces the
  three-resolution escalation.
- **Done when:** dry-run on a fixture with `partial` verdict aborts;
  dry-run on this feature passes through.

## T7 — Wire build entry and plan approval

- **Output:** `shared/skills/agent-team-protocol/SKILL.md` carries the
  build-agent first-action directive.
  `shared/skills/spec-workflow/SKILL.md` declares `origin:` as a
  required plan.md frontmatter key.
  `shared/skills/phase-workflow/SKILL.md` documents the alignment-gate
  step before peer review.
- **Done when:** the three SKILL.md files are updated and
  `scripts/generate.sh` regenerates adapter artifacts that include the
  updated wording.

## T8 — Slash command

- **Output:** `claude_code/.claude/commands/origin-check.md` (source)
  and `adapters/claude-code/.claude/commands/origin-check.md`
  (distribution). Both call `scripts/check-origin-alignment.sh
  <feature-id>` and surface the three-resolution `AskUserQuestion`
  prompt on exit ≥ 2.
- **Done when:** `/origin-check origin-confirmation-circuit-breaker`
  prints the alignment block and exits 0.

## T9 — Backfill existing specs

- **Output:** Every existing `specs/*/plan.md` carries an `origin:`
  block.
  - `llm-wiki-groundwork` → `issue: gosha70/code-copilot-team#12`.
  - `wiki-ingest-pipeline` → `issue: gosha70/code-copilot-team#28`,
    plus `origin_claim` quoting the user's actual ask (the
    derailment-target).
  - `memkernel-integration`, `infra-verification-gate`,
    `sdd-sprint-1`, `code-reviewer-assistant`,
    `pitches/0001-shape-up-support` → set origin or mark
    `origin: { type: internal, reason: "..." }`.
- **Done when:** `validate-spec.sh --all` exits 0 and
  `IMPLEMENTATION_STATUS.md` records the per-spec exit code from the
  alignment script.

## T10 — Tests

- **Output:** `tests/test-origin-alignment.sh` covering all six exit
  codes; `tests/test-shared-structure.sh` updated counts (`exactly 21
  skills`, README "21 skills" assertion) plus the `SKILL_NAMES`
  array; `tests/test-generate.sh` updated counts (21 .mdc files) and
  case-statement extensions; `tests/test-counts.env` recalibrated.
- **Done when:** all four test scripts exit 0 and the recalibration
  is derived from observed counts, not guessed.

## T11 — Documentation

- **Output:** `knowledge/README.md` "Origin alignment" section;
  `knowledge/wiki/workflows/origin-alignment.md` workflow page (lints
  clean); `claude_code/.claude/rules/coding-standards.md`
  "Verification Discipline" bullet; both top-level `CLAUDE.md` files
  one-line directive.
- **Done when:** `bash knowledge/wiki/scripts/lint-wiki.sh` exits 0
  and the new content is reviewed.

## T12 — Self-dogfood + verification suite

- **Output:** alignment record at
  `specs/origin-confirmation-circuit-breaker/origin-alignment-<YYYY-MM-DD-HHMM>.md`
  with `Verdict: aligned, high`.
- **Done when:**
  - `scripts/check-origin-alignment.sh origin-confirmation-circuit-breaker`
    exits 0.
  - `scripts/check-origin-alignment.sh wiki-ingest-pipeline` exits 3
    (`derailed`) — the proof that the breaker catches the failure
    that motivated it.
  - All test scripts exit 0.
  - `scripts/generate.sh` runs cleanly.
  - `bash knowledge/wiki/scripts/lint-wiki.sh` exits 0.
  - User has reviewed `git diff` and given explicit go before commit.
