---
spec_mode: full
feature_id: visual-review-ui-harness
risk_category: feature
status: draft
date: 2026-07-04
---

# Spec: UI-Enhancement Agent Harness (Visual Review)

<!-- Project constitution: shared/skills/ — copilot-conventions, coding-standards, safety -->

Origin: gosha70/code-copilot-team#66 (authoritative `origin:` block in plan.md frontmatter).

## User Scenarios

### US1: Copilot builds a non-generic frontend (Priority: HIGH)

**Given** a copilot (Claude Code / Cursor / Codex / Copilot / Windsurf / Aider) starts UI work in a project with the harness installed
**When** it reads the `design-system` skill and the committed `DESIGN.md` + `design/tokens.json` bundle
**Then** it derives a domain-fit direction, overrides the four framework defaults (neutral/accent/font/radius), and builds against semantic tokens — so the output is bespoke by construction, not the training-data mean.

### US2: The rendered UI is gated by a closed visual-review loop (Priority: HIGH)

**Given** UI has been built against the bundle
**When** the copilot runs `npm run copilot:review`
**Then** the harness boots the app, runs the axe-core WCAG 2.2 AA gate + deterministic anti-slop rubric, screenshots at 375/768/1440, and a critic scores the result against `DESIGN.md`; the loop iterates (cap 3) until the design bar is met or hands residual findings to the human.

### US3: The loop serves every adapter, not just Claude Code (Priority: MEDIUM)

**Given** a non-Claude copilot with no multimodal agent
**When** it runs the harness with `CRITIC=vision`
**Then** the runner calls a vision LLM over HTTPS (provider/key from env) and gates via exit code — same rubric, same gates as the Claude Code agent critic.

### US4: Absent Playwright degrades cleanly (Priority: MEDIUM)

**Given** an environment without Playwright/Chromium
**When** the harness runs
**Then** it never auto-installs, runs an HTTP-200 smoke only (the DOM rubric and screenshot critique need a browser and are SKIPPED), and reports the visual pass as SKIP — while a dead dev server still fails (SKIP must not become a false pass).

## Requirements

- **FR-001**: The system MUST ship two on-demand skills — `design-system` and `visual-review` — in `shared/skills/`, propagated to all six adapters by `scripts/generate.sh`.
- **FR-002**: The `design-system` skill MUST encode domain→direction derivation, the four-default override, the anti-slop catalog, layout grammar, and required component states.
- **FR-003**: The system MUST ship a tool-agnostic runner at `shared/templates/ui-harness/harness/` (Playwright + `@axe-core/playwright` gate + anti-slop rubric + pluggable critic) that type-checks and runs.
- **FR-004**: The harness MUST support a pluggable critic — agent mode (emit artifacts for a multimodal agent) and vision mode (HTTPS vision LLM, provider/key from env) — with no hard SDK dependency.
- **FR-005**: The system MUST ship a committed steering bundle — `DESIGN.md` + `design/tokens.json` (DTCG, defaults overridden) — deployable via the existing `setup.sh` template loop.
- **FR-006**: A `visual-reviewer` agent MUST exist, authored in `claude_code/.claude/agents/` and synced to `adapters/claude-code/.claude/agents/` by `generate.sh`.
- **FR-007**: The `web-dynamic` and `web-static` templates MUST reference the bundle and run `copilot:review` in their QA role.
- **FR-008**: The harness MUST NOT auto-install Playwright; when it is absent it MUST degrade to an HTTP-200 smoke and report the visual critique and DOM rubric as SKIP. A dead dev server MUST still fail — SKIP must not become a false pass. The runner MUST also degrade (not crash) when the `playwright` package itself is absent.
- **FR-009**: The axe-core gate MUST use WCAG 2.2 AA tags and fail on zero critical/serious violations before the aesthetic critic runs.
- **FR-010**: `test-generate.sh` and `test-shared-structure.sh` MUST pass with counts updated to reflect the additions; the adapter drift gate MUST be clean.

## Constraints / What NOT to Build

- **Scope guard**: This workstream MUST NOT modify session-analytics code, the benchmark harness, or any unrelated generated outputs — except through the intended `shared/*` → `generate.sh` → `adapters/*` path. This keeps the post-rebase commit reviewable.
- No backend/security changes — the harness governs appearance and structure only; `security-review` stays in the loop for auth/data paths.
- No stack-adapter generator, no DTCG→Style-Dictionary build pipeline, no `/ui-enhance` retrofit command, no dedicated dashboard skeleton, no perceptual (Chromatic/Percy) diffing — deferred to a later "Max" tier.
- No always-on skills — both new skills are on-demand (web-only; would waste context on Java/ML/CLI projects).

## Key Entities

- **Steering bundle**: `DESIGN.md` (prose + machine-readable front-matter) + `design/tokens.json` (DTCG primitive→semantic) — the committed art-direction boundary.
- **Harness**: `shared/templates/ui-harness/harness/` — `runner.ts` (orchestrator), `audit.ts` (a11y gate), `rubric.ts` (anti-slop pre-filter).
- **Critic**: the aesthetic judge — the `visual-reviewer` agent (Claude Code) or a vision-LLM call (other adapters).
- **Anti-slop catalog**: the enumerated tells→remedies bans enforced by the skill and the rubric.

## Success Criteria

1. US1 demonstrable: a copilot reads the bundle and emits token-driven UI with no default accent/font/radius (verified by the rubric's default-token detection).
2. FR-001 verified: `generate.sh` propagates both skills to Cursor (23 `.mdc`), Codex TOC, GitHub Copilot (17 on-demand).
3. FR-003/004/008 verified: `tsc --noEmit` clean; the runner executes end-to-end and emits the `critique-feedback.json` contract; absent-Playwright path SKIPs.
4. FR-010 verified: `test-generate.sh` PASS (290) and `test-shared-structure.sh` PASS (810); adapter drift gate clean.
5. Scope guard verified: `git diff` touches only UI-harness paths + the intended generated outputs — no session-analytics/benchmark files.
