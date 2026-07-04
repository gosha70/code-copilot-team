---
spec_mode: full
feature_id: visual-review-ui-harness
risk_category: feature
justification: |
  Additive capability wired through the existing generation path: two on-demand
  skills (shared/skills → generate.sh → 6 adapters), one new template
  (shared/templates/ui-harness) carrying a shippable Node/TS runner, one
  Claude Code agent (claude_code/.claude/agents → synced to adapters), and
  template wiring for web-dynamic/web-static. Touches generate.sh (agent-sync
  generalization + one glob case) and the two test suites' expected counts.
  spec_mode=full because it adds a new user-facing capability, ships executable
  artifacts (the harness), and changes the generation pipeline + test gates.
status: draft
date: 2026-07-04
issue: 66
origin:
  issue: gosha70/code-copilot-team#66
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/66
  origin_claim: |
    Issue #66 (feat: add visual review UI harness) asks for a reusable
    UI-Enhancement Agent Harness that makes copilot-generated UI unique,
    on-brand, and release-grade rather than generic ("AI-slop"). Root cause per
    three independent local research reports (Claude/Gemini/OpenAI):
    distributional convergence — fixed only by pre-committed constraints + a
    verification loop. Scope: design-system + visual-review skills across all 6
    adapters; a tool-agnostic ui-harness template (DESIGN.md + DTCG tokens +
    Playwright/axe/rubric runner with a pluggable critic); a Claude Code
    visual-reviewer agent; web-template wiring.

    User-confirmed scope decisions (this planning session):
      - Appetite: FULL closed loop (steering + skills + closed visual-review
        loop + web-template wiring + one visual-reviewer agent).
      - Delivery: shippable tool-agnostic harness/ runner deployed into projects
        via the template, callable by ANY copilot as `npm run copilot:review`.
      - Deferred to a later "Max" tier: stack-adapter generator,
        DTCG→Style-Dictionary pipeline, /ui-enhance command, dashboard skeleton,
        perceptual diffing.

    Scope guard (user-set): must not modify session-analytics, benchmark
    harness, or unrelated generated outputs except through the intended
    shared/* → generate.sh → adapters/* path.
---

# Plan: UI-Enhancement Agent Harness (Visual Review)

## Architecture — four planes, each on a concrete repo mechanism

```
1. Steering bundle     DESIGN.md + design/tokens.json   → shared/templates/ui-harness (setup.sh deploy)
2. Craft intelligence  design-system + visual-review     → shared/skills/* → generate.sh → 6 adapters
3. Verification runtime harness/ (runner+audit+rubric)    → shipped in the ui-harness template
4. CC accelerator      visual-reviewer agent             → claude_code + adapters/claude-code/.claude/agents
```

**Design principle:** split the loop into a deterministic harness (boot, screenshot,
axe, rubric — identical for every copilot) and a pluggable critic (agent for Claude
Code, vision-LLM for others). Same rubric/gates/exit-criteria; only the critic swaps.

## Files

- `shared/skills/design-system/SKILL.md`, `shared/skills/visual-review/SKILL.md`
- `shared/templates/ui-harness/{PROJECT.md, DESIGN.md, design/tokens.json, commands/team-review.md, harness/{package.json, tsconfig.json, src/{runner,audit,rubric}.ts}}`
- `claude_code/.claude/agents/visual-reviewer.md` (+ synced `adapters/claude-code/.claude/agents/visual-reviewer.md`)
- `scripts/generate.sh` — generalize the claude_code→adapter agent sync (`verify-app.md visual-reviewer.md`); add a frontend glob case for the two skills
- `shared/templates/web-dynamic/PROJECT.md`, `shared/templates/web-static/PROJECT.md` — bundle reference + QA `copilot:review`
- `tests/test-counts.env` (290, 810), `tests/test-generate.sh`, `tests/test-shared-structure.sh`, `README.md` (skill/test counts)

## Hook points (no new phase)

- **Plan** — `design-system` derives `DESIGN.md`, approved at the existing plan gate.
- **Build** — the frontend specialist reads the bundle, wires tokens, lays down `harness/`.
- **Review** — `visual-reviewer` runs the loop; other copilots run `npm run copilot:review`.

## Verification

- `generate.sh` idempotent; `git diff --exit-code adapters/` clean once committed.
- `test-generate.sh` PASS (290); `test-shared-structure.sh` PASS (810) against a synced install (calibrated in an isolated `$HOME` to avoid touching the live `~/.claude`).
- Harness `tsc --noEmit` clean; runner executed once (emits `critique-feedback.json`); absent-Playwright SKIP path.
