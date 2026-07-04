# Tasks: UI-Enhancement Agent Harness (Visual Review)

Feature: visual-review-ui-harness · Issue: gosha70/code-copilot-team#66

Status legend: [x] done · [ ] todo

## T1 — Craft skills (portable to all 6 adapters)
- [x] T1.1 `shared/skills/design-system/SKILL.md` (derivation, four-default override, anti-slop catalog, layout grammar, states) — FR-001, FR-002
- [x] T1.2 `shared/skills/visual-review/SKILL.md` (loop, rubric, a11y gate, exit criteria) — FR-001
- [x] T1.3 `generate.sh` propagates both (Cursor 23 `.mdc`, Codex TOC, GH Copilot 17 on-demand w/ frontend glob) — FR-001 ✓ verified

## T2 — Steering bundle starters
- [x] T2.1 `shared/templates/ui-harness/DESIGN.md` (sections + Do/Don'ts + machine front-matter) — FR-005
- [x] T2.2 `shared/templates/ui-harness/design/tokens.json` (DTCG primitive→semantic, defaults overridden) — FR-005

## T3 — Tool-agnostic runner
- [x] T3.1 `harness/src/audit.ts` (`@axe-core/playwright`, WCAG 2.2 AA, zero-critical gate) — FR-009
- [x] T3.2 `harness/src/rubric.ts` (deterministic anti-slop pre-filter) — FR-003
- [x] T3.3 `harness/src/runner.ts` (orchestrator, pluggable critic, degradation) — FR-003, FR-004, FR-008
- [x] T3.4 `harness/{package.json, tsconfig.json}` + `PROJECT.md` + `commands/team-review.md`
- [x] T3.5 `tsc --noEmit` clean + runner executed once (emits `critique-feedback.json`) ✓ verified

## T4 — Claude Code critic
- [x] T4.1 `claude_code/.claude/agents/visual-reviewer.md` (opus, multimodal) — FR-006
- [x] T4.2 `generate.sh` agent-sync generalized → `adapters/claude-code/.claude/agents/visual-reviewer.md` — FR-006 ✓ verified

## T5 — Template wiring
- [x] T5.1 `web-dynamic/PROJECT.md` — bundle section + Frontend/QA role edits — FR-007
- [x] T5.2 `web-static/PROJECT.md` — bundle section + Frontend/QA role edits — FR-007

## T6 — Plumbing & gates
- [x] T6.1 Regenerate adapters (`generate.sh`); drift gate clean — FR-010
- [x] T6.2 `tests/test-shared-structure.sh` — ui-harness assertion block; dir-count 12→13; skills 21→23; README count
- [x] T6.3 `tests/test-generate.sh` — cursor 21→23, gh-copilot 15→17 (×2)
- [x] T6.4 `tests/test-counts.env` — 290 / 810; `README.md` — 23 skills, 290/810 tests
- [x] T6.5 Both suites green (290 / 810, isolated synced `$HOME`) ✓ verified

## Out of scope (Max tier — not built)
- [ ] Stack-adapter generator · DTCG→Style-Dictionary pipeline · `/ui-enhance` command · dashboard skeleton · perceptual diffing
