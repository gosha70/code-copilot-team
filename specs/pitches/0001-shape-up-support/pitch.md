---
pitch_id: 0001-shape-up-support
title: "Add Shape-Up methodology support"
appetite: 6w
bet_status: shaping
cycle: ""
circuit_breaker: "If S4 (cycle-retro/cooldown-report agents) is still uphill at week 4, ship S1+S2+S3 and shelve S4 to the next cycle."
shaped_by: "gosha70"
shaped_date: 2026-05-02
---

# Pitch: Add Shape-Up methodology support

## Problem

`code-copilot-team` ships first-class Spec-Driven Development (SDD) support but no
native Shape-Up vocabulary. SDD answers *"how do we know we built the right
thing?"*; it does not answer *"what do we build next, and how big should it be?"* —
that's what Shape-Up provides. Today the toolkit is usable for feature-shaped
work (clear requirement → plan → build → ship) but not for product-shaped work
(rough idea → shape → bet → cycle → ship-or-shelve). Closing that gap makes the
scaffold viable for greenfield product development, not just feature delivery.

## Appetite

**6w** — Four agents, five slash commands, four templates, one validator, plus
docs and CI wiring. A 4w bet would force shedding either `cycle-retro` or
`cooldown-report` (the two highest-uphill scopes), which would leave Shape-Up
support without a closing-the-loop story. A 2w bet only fits S1.

## Solution shape

Nest Shape-Up artifacts above SDD: `specs/pitches/<id>/` holds `pitch.md`
(Shape-Up) plus `plan.md`/`spec.md`/`tasks.md` (SDD) plus `hill.json` (per-scope
status). The pitch describes the *bet*; SDD's plan/spec/tasks describe the
*implementation* underneath one or more scopes of that pitch. Adapter-side, four
new agents (`pitch-shaper`, `scope-executor`, `cycle-retro`, `cooldown-report`)
and five new slash commands (`/shape`, `/bet`, `/cycle-start`, `/hill`,
`/cooldown`) drive the workflow. CI gains `validate-pitch.sh` to enforce
frontmatter, mirroring the existing `validate-spec.sh` pattern.

The first dogfood case is *this pitch itself* — the work to add Shape-Up support
runs as `0001-shape-up-support`, proving the layout on a real bet before
downstream consumers adopt it.

## Scopes

### S1: Foundation — templates, validator, dogfood pitch artifacts

`shared/templates/sdd/{pitch-template.md, hill-chart.json,
cycle-retro-template.md, cooldown-report-template.md}` plus
`scripts/validate-pitch.sh` plus `specs/pitches/0001-shape-up-support/{pitch,
plan, spec, tasks}.md`. Unblocks every other scope. Self-contained — no agent
or command conventions involved.

### S2: Shaping & betting agents and commands

`pitch-shaper` agent + `/shape <topic>` + `/bet <pitch-id>`. The "before-cycle"
half of the workflow. Exercise: produce a second pitch end-to-end via `/shape`
and lock it via `/bet`.

### S3: Cycle execution agent and commands

`scope-executor` agent (adapter on top of `build`) + `/cycle-start <pitch-id>` +
`/hill <scope> <up|down|done>`. The "during-cycle" half. Exercise: execute one
scope of an existing pitch end-to-end with hill chart updates.

### S4: Closing-the-loop agents and commands

`cycle-retro` agent + `cooldown-report` agent + `/cooldown` command. Generates
`specs/retros/cycle-NN.md` and the cooldown report. Highest-uphill scope —
depends on git-log + hill.json + pitch parsing. First candidate for the
circuit breaker.

### S5: CI wiring + documentation

Wire `validate-pitch.sh` into `.github/workflows/sync-check.yml` (only when
`specs/pitches/` exists). Extend `validate-spec.sh` to also walk
`specs/pitches/*/` so nested SDD artifacts get validated. Write
`docs/shape-up-workflow.md` and add Shape-Up coverage to the README scorecard.

## Rabbit holes

- **Hill-chart visualization beyond JSON**: terminal/IDE rendering of the hill
  curve. Tempting but slow. Workaround: ship the JSON file and an ASCII-printable
  summary inside `cycle-retro`; defer real rendering to a future pitch.
- **`scope-executor` becoming a fork of `build`**: the temptation is to copy
  `build.md` and tweak it. Workaround: make `scope-executor` a thin adapter that
  reads pitch context, then delegates to the existing `build` agent for the
  actual work. One `build` codebase, not two.
- **Frontmatter schema drift between `pitch.md` and SDD `plan.md`**: easy to
  introduce conflicting fields. Workaround: pitch frontmatter uses a
  non-overlapping namespace (`pitch_id`, `appetite`, `bet_status`, `cycle`,
  `circuit_breaker`); SDD `plan.md` keeps its existing fields unchanged.
- **`validate-spec.sh` regression**: extending it to walk nested pitch dirs
  could break existing top-level specs. Workaround: additive change only —
  validate `specs/*/` first (existing behavior), then `specs/pitches/*/` if
  present.

## No-gos

- No tooling for distributed teams (multi-person bets, async betting tables) —
  solo/small-team is enough for v1.
- No integration with external trackers (Linear, GitHub Projects) — local-first.
- No retroactive migration of existing `specs/<feature-id>/` dirs to
  `specs/pitches/<id>/`. They stay where they are; pitches are additive.
- No new "appetite enforcement" agent that polices time. The circuit breaker is
  social, not automated, in v1.

## Circuit breaker

If S4 (cycle-retro + cooldown-report) is still uphill at week 4 of the 6w
appetite, ship S1+S2+S3+S5 and shelve S4 to the next cycle. "Uphill at week 4"
means: either agent file does not parse `git log` + `hill.json` end-to-end into
a generated retro/report on a real cycle. The minimum viable Shape-Up
toolkit is shaping → betting → cycling; closing-the-loop is valuable but
shippable later. S1–S3 + S5 alone deliver a usable workflow; S4 only adds
automation on top of artifacts the user can write by hand.

## Bet log

| Date | bet_status | Note |
|------|------------|------|
| 2026-05-02 | shaping | Pitch drafted from issue #13. Dogfood case for the new templates. |
