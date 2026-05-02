---
spec_mode: full
feature_id: 0001-shape-up-support
risk_category: integration
justification: "Framework-level change: new agents, slash commands, templates, CI validators, and a new top-level directory convention (specs/pitches/). Touches generation pipeline and adapter outputs."
status: draft
date: 2026-05-02
collaboration_mode: single
---

# Implementation Plan: Shape-Up methodology support

**Branch**: `feature/0001-shape-up-support`
**Input**: specs/pitches/0001-shape-up-support/spec.md, specs/pitches/0001-shape-up-support/pitch.md

## Summary

Add Shape-Up methodology support to `code-copilot-team`: pitch templates, hill
chart, cycle/cooldown retros, four agents, five slash commands, a frontmatter
validator, CI wiring, and methodology docs. Nests SDD artifacts under
`specs/pitches/<id>/` so a pitch describes the bet and SDD describes the
implementation underneath. The pitch at
`specs/pitches/0001-shape-up-support/` is itself the first dogfood case.

## Technical Context

**Language/Version**: Bash (validators, generation), Markdown (templates,
agents, commands, docs), JSON (hill chart schema)
**Primary Dependencies**: `scripts/validate-spec.sh`, `scripts/generate.sh`,
`shared/templates/sdd/`, adapter agent/command directories under
`adapters/*/.claude/` and `claude_code/.claude/`, `.github/workflows/sync-check.yml`
**Testing**: bash tests under `tests/` (existing pattern: test-generate.sh,
test-shared-structure.sh). New: `tests/test-validate-pitch.sh`.
**Constraints**: All adapter changes must flow through `shared/` →
`scripts/generate.sh` → `adapters/`. Pitch frontmatter must not collide with
SDD plan.md frontmatter. `validate-spec.sh` extension must be strictly additive
(no regression on existing top-level specs).

## Constitution Check

| Rule file | Concern | Status |
|-----------|---------|--------|
| `coding-standards.md` | No magic strings (frontmatter values defined as constants in validator), shell uses `set -euo pipefail` | OK |
| `safety.md` | Validators are read-only; no destructive ops; no secrets | OK |
| `copilot-conventions.md` | One logical change per scope/commit; repo is source of truth (no external pitch tracking) | OK |

## Architecture Decisions

### ADR-1: Nested layout (`specs/pitches/<id>/{pitch.md, plan.md, ...}`)

**Context**: The issue offered two layouts — nested (SDD inside pitches) or
parallel (`specs/pitches/` and `specs/sdd/<id>/` separate). Nested coheres the
artifacts that describe one bet; parallel keeps `validate-spec.sh` untouched.

**Decision**: Nested. SDD artifacts produced for a pitch live under that
pitch's directory.

**Consequences**: `validate-spec.sh` must be extended to walk
`specs/pitches/*/` in addition to `specs/*/`. Done as a strictly additive
change (validates new path only if it exists). Existing `specs/<feature-id>/`
dirs continue to work unchanged — they are not migrated.

### ADR-2: `scope-executor` is an adapter, not a fork of `build`

**Context**: A scope inside a pitch is implemented just like any other build
task, plus pitch context. Forking `build.md` would create two codebases to
maintain.

**Decision**: `scope-executor.md` reads pitch + scope context, updates
`hill.json`, and delegates the actual implementation to the existing `build`
agent. Thin adapter, no logic duplication.

**Consequences**: Build behavior stays canonical in one file. `scope-executor`
remains small and focused on Shape-Up bookkeeping (status transitions,
hill.json updates, pitch frontmatter reads).

### ADR-3: Disjoint frontmatter namespaces (pitch vs. plan)

**Context**: `pitch.md` and `plan.md` will live in the same directory. Shared
field names (e.g. both having `status`) would create ambiguity for validators
and humans.

**Decision**: Pitch frontmatter uses Shape-Up-specific fields (`pitch_id`,
`appetite`, `bet_status`, `cycle`, `circuit_breaker`, `shaped_by`,
`shaped_date`). Plan frontmatter is unchanged from the existing SDD template
(`spec_mode`, `feature_id`, `risk_category`, `justification`, `status`, `date`).

**Consequences**: Validators are independent. `validate-pitch.sh` only reads
pitch.md; `validate-spec.sh` only reads plan.md. No cross-file coupling
required.

### ADR-4: `validate-pitch.sh` mirrors `validate-spec.sh` style

**Context**: There's already a working pattern for spec validators (per-dir
walk, `extract_frontmatter_field` helper, `pass`/`fail` counters,
`--all`/`--single` CLI).

**Decision**: New validator mirrors that exact shape. Same flag names, same
helper functions, same output format.

**Consequences**: Future maintainers learn one validator and know both. CI
wiring follows the same pattern.

## Project Structure

```
shared/templates/sdd/pitch-template.md            — Shape-Up pitch template (S1)
shared/templates/sdd/hill-chart.json              — Hill chart JSON schema (S1)
shared/templates/sdd/cycle-retro-template.md      — Cycle retrospective template (S1)
shared/templates/sdd/cooldown-report-template.md  — Cooldown report template (S1)
specs/pitches/0001-shape-up-support/pitch.md      — Dogfood pitch (S1)
specs/pitches/0001-shape-up-support/plan.md       — This file (S1)
specs/pitches/0001-shape-up-support/spec.md       — SDD spec for the pitch (S1)
specs/pitches/0001-shape-up-support/tasks.md      — Task breakdown (S1)
scripts/validate-pitch.sh                         — Pitch frontmatter validator (S1)

shared/agents/pitch-shaper.md                     — Pitch-shaper agent (S2)
shared/commands/shape.md                          — /shape <topic> (S2)
shared/commands/bet.md                            — /bet <pitch-id> (S2)

shared/agents/scope-executor.md                   — Scope executor (S3)
shared/commands/cycle-start.md                    — /cycle-start <pitch-id> (S3)
shared/commands/hill.md                           — /hill <scope> <status> (S3)

shared/agents/cycle-retro.md                      — Cycle retro agent (S4)
shared/agents/cooldown-report.md                  — Cooldown report agent (S4)
shared/commands/cooldown.md                       — /cooldown (S4)

scripts/validate-spec.sh                          — Extended to walk specs/pitches/*/ (S5)
.github/workflows/sync-check.yml                  — Wire validate-pitch.sh (S5)
docs/shape-up-workflow.md                         — Methodology overview (S5)
README.md                                         — Scorecard update (S5)
tests/test-validate-pitch.sh                      — Validator tests (S5)
```

## Scope

### Task S1.1: Pitch templates (this scope, this session)

**Files**: `shared/templates/sdd/pitch-template.md`, `hill-chart.json`,
`cycle-retro-template.md`, `cooldown-report-template.md`

**Acceptance criteria**:
- [x] Four template files exist under `shared/templates/sdd/`
- [x] Pitch frontmatter includes `pitch_id`, `appetite`, `bet_status`, `cycle`,
  `circuit_breaker`, `shaped_by`, `shaped_date`
- [x] Hill chart JSON has a `$schema`, validates the example, includes scope
  status enum `uphill | downhill | done`
- [x] Templates use the same comment/instruction style as existing SDD templates

### Task S1.2: Dogfood pitch artifacts (this scope, this session)

**Files**: `specs/pitches/0001-shape-up-support/{pitch.md, plan.md, spec.md, tasks.md}`

**Acceptance criteria**:
- [x] `pitch.md` instantiates `pitch-template.md`, frontmatter complete
- [x] `plan.md` follows existing SDD `plan-template.md` frontmatter (spec_mode=full)
- [x] `spec.md` has User Scenarios, Requirements, Constraints sections, no
  unresolved [NEEDS CLARIFICATION]
- [x] `tasks.md` decomposes scopes S1–S5 into trackable tasks; sub-issue source
  of truth for #13 follow-ups

### Task S1.3: `validate-pitch.sh` (this scope, this session)

**Files**: `scripts/validate-pitch.sh`

**Acceptance criteria**:
- [x] Exits 0 when run against `specs/pitches/0001-shape-up-support/pitch.md`
- [x] Enforces `appetite ∈ {2w, 4w, 6w}`
- [x] Enforces `bet_status ∈ {shaping, shaped, bet, building, shipped, shelved}`
- [x] Requires `circuit_breaker` non-empty (for `bet_status` ≥ `shaped`)
- [x] Requires `cycle` non-empty when `bet_status` ∈ {bet, building, shipped}
- [x] Mirrors `validate-spec.sh` CLI flags (`--all`, `--pitch-id`)
- [x] Passes `bash -n scripts/validate-pitch.sh`

### Task S2.1: `pitch-shaper` agent + `/shape` command (next session)

Deferred to a follow-up sub-issue. See tasks.md for the full breakdown.

### Task S2.2: `/bet` command (next session)

Deferred. See tasks.md.

### Task S3.1: `scope-executor` agent + `/cycle-start` + `/hill` (next session)

Deferred. See tasks.md.

### Task S4.1: `cycle-retro` agent (next session)

Deferred. See tasks.md.

### Task S4.2: `cooldown-report` agent + `/cooldown` (next session)

Deferred. See tasks.md.

### Task S5.1: CI wiring + `validate-spec.sh` extension + docs (next session)

Deferred. See tasks.md.

## Constraints / What NOT to Build

- No retroactive migration of `specs/<feature-id>/` dirs into
  `specs/pitches/<id>/`. Pitches are additive.
- No automated appetite enforcement. Circuit breakers are social.
- No fork of `build.md` for `scope-executor` — adapter only (ADR-2).
- No external tracker integration (Linear, GitHub Projects) — local-first.
- No hill-chart visualization beyond JSON in v1.

## File Ownership (Non-Overlapping)

| Owner | Files |
|-------|-------|
| Templates (S1) | `shared/templates/sdd/{pitch,hill-chart,cycle-retro,cooldown-report}*` |
| Pitch dogfood (S1) | `specs/pitches/0001-shape-up-support/*` |
| Validator (S1) | `scripts/validate-pitch.sh` |
| Agents — shaping (S2) | `shared/agents/pitch-shaper.md`, `shared/commands/{shape,bet}.md` |
| Agents — execution (S3) | `shared/agents/scope-executor.md`, `shared/commands/{cycle-start,hill}.md` |
| Agents — closing (S4) | `shared/agents/{cycle-retro,cooldown-report}.md`, `shared/commands/cooldown.md` |
| CI + docs (S5) | `scripts/validate-spec.sh`, `.github/workflows/sync-check.yml`, `docs/shape-up-workflow.md`, `README.md` |

## Collaboration (Dual Mode)

Single. No peer-provider review configured for this pitch.
