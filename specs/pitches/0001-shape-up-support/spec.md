---
spec_mode: full
feature_id: 0001-shape-up-support
risk_category: integration
status: draft
date: 2026-05-02
---

# Spec: Shape-Up methodology support

## User Scenarios

### US1: Shape a rough idea into a pitch (Priority: HIGH)

**Given** a user has a rough product idea and wants a Shape-Up pitch
**When** they run `/shape <topic>`
**Then** the `pitch-shaper` agent asks clarifying questions and writes
`specs/pitches/<NNNN-slug>/pitch.md` with frontmatter `bet_status: shaped`,
populated appetite, scopes (3–7), rabbit holes, no-gos, and a circuit breaker

### US2: Lock a shaped pitch as a bet (Priority: HIGH)

**Given** a `pitch.md` exists with `bet_status: shaped`
**When** the user runs `/bet <pitch-id>`
**Then** the pitch frontmatter is updated to `bet_status: bet`, `cycle: <NN>`
is set, and the bet log gets a new row

### US3: Start a cycle and track scopes on the hill chart (Priority: HIGH)

**Given** a pitch with `bet_status: bet`
**When** the user runs `/cycle-start <pitch-id>`
**Then** `specs/pitches/<id>/hill.json` is created with all scopes at
`status: uphill`, and frontmatter moves to `bet_status: building`

**Given** a pitch is `building` and the user is working on scope S2
**When** they run `/hill S2 down`
**Then** `hill.json` updates `S2.status` from `uphill` to `downhill` with a
new `last_updated` timestamp

### US4: Execute a scope (Priority: HIGH)

**Given** a pitch is `building` and the user wants to implement scope S1
**When** they invoke `scope-executor` for S1
**Then** the agent reads `pitch.md` for context, delegates implementation to
the existing `build` agent, and updates `hill.json` as scope progresses

### US5: Generate a cycle retrospective (Priority: MEDIUM)

**Given** a cycle has ended and one or more pitches were active
**When** the user runs the cycle-retro flow
**Then** `specs/retros/cycle-NN.md` is generated from `pitch.md`, `hill.json`,
and `git log`, summarizing bets, hill chart final state, and inputs to the
next betting table

### US6: Generate a cooldown report (Priority: MEDIUM)

**Given** a cooldown period has ended
**When** the user runs `/cooldown`
**Then** `cooldown-report` agent summarizes bug fixes, identifies pitches
ready for the next betting table, and the active pitch's `bet_status` is set
to `shipped` or `shelved`

### US7: CI validates pitch frontmatter (Priority: HIGH)

**Given** `specs/pitches/` exists in a repo
**When** CI runs `sync-check.yml`
**Then** `validate-pitch.sh` executes against every pitch and fails the build
if any frontmatter field is missing, has an invalid value, or violates a
conditional rule (e.g. `cycle` empty when `bet_status: bet`)

### US8: Co-existence with existing SDD specs (Priority: HIGH)

**Given** the repo already has `specs/<feature-id>/` directories from before
Shape-Up support
**When** Shape-Up support is added
**Then** existing specs continue to validate via `validate-spec.sh` with no
changes required, and `validate-spec.sh` *also* walks `specs/pitches/*/` to
validate nested SDD artifacts

## Requirements

- **FR-001**: System MUST provide four templates under `shared/templates/sdd/`:
  `pitch-template.md`, `hill-chart.json`, `cycle-retro-template.md`,
  `cooldown-report-template.md`.
- **FR-002**: Pitch frontmatter MUST contain `pitch_id`, `title`, `appetite`,
  `bet_status`, `cycle`, `circuit_breaker`, `shaped_by`, `shaped_date`.
- **FR-003**: `appetite` MUST be one of `{2w, 4w, 6w}`.
- **FR-004**: `bet_status` MUST be one of
  `{shaping, shaped, bet, building, shipped, shelved}`.
- **FR-005**: `cycle` MUST be non-empty whenever `bet_status` is `bet` or any
  later status in the lifecycle (`building`, `shipped`).
- **FR-006**: `circuit_breaker` MUST be a non-empty string for any pitch in
  status `shaped` or later.
- **FR-007**: System MUST provide `scripts/validate-pitch.sh` enforcing FR-002
  through FR-006, supporting `--all` (default) and `--pitch-id <id>` CLI flags.
- **FR-008**: System MUST provide a `pitch-shaper` agent that asks clarifying
  questions, produces a pitch with 3–7 scopes, and writes
  `specs/pitches/<id>/pitch.md` with `bet_status: shaped`.
- **FR-009**: System MUST provide a `scope-executor` agent that reads pitch
  context, updates `hill.json`, and delegates to the existing `build` agent for
  implementation (no fork of `build.md`).
- **FR-010**: System MUST provide a `cycle-retro` agent that generates
  `specs/retros/cycle-NN.md` from `pitch.md`, `hill.json`, and `git log`.
- **FR-011**: System MUST provide a `cooldown-report` agent that summarizes
  cooldown bug fixes and lists pitches ready for the next betting table.
- **FR-012**: System MUST provide slash commands `/shape`, `/bet`,
  `/cycle-start`, `/hill`, `/cooldown` invoking the corresponding agents.
- **FR-013**: System MUST extend `validate-spec.sh` to walk `specs/pitches/*/`
  for nested SDD artifacts, additively (existing `specs/*/` walk unchanged).
- **FR-014**: CI workflow `sync-check.yml` MUST run `validate-pitch.sh` when
  `specs/pitches/` exists in the repo.
- **FR-015**: System MUST provide `docs/shape-up-workflow.md` describing the
  methodology, schema, and when to use SDD-only vs. Shape-Up + SDD.
- **FR-016**: System MUST NOT fork or duplicate `build.md` logic in
  `scope-executor`; the executor is a thin adapter.
- **FR-017**: System MUST NOT migrate existing `specs/<feature-id>/` directories
  into `specs/pitches/<id>/`. Layout change is additive only.

## Constraints / What NOT to Build

- No multi-person bets, distributed betting tables, or async vote tooling. Solo
  / small-team only in v1.
- No hill-chart visualization beyond the JSON file (terminal/IDE rendering is a
  future enhancement).
- No external tracker integration (Linear, GitHub Projects) in v1.
- No automated appetite/circuit-breaker enforcement — social, not automated.
- No new global agents beyond the four named here.

## Key Entities

- **Pitch**: a shaped problem + rough solution + appetite, persisted as
  `specs/pitches/<id>/pitch.md`. Identified by `pitch_id`.
- **Appetite**: fixed time-budget for a pitch. One of `2w`, `4w`, `6w`.
- **Bet**: a pitch that has been chosen for the next cycle. Reflected by
  `bet_status: bet` and a populated `cycle` field.
- **Cycle**: the uninterrupted build period at the appetite. Identified by a
  cycle number (e.g. `01`).
- **Cooldown**: the 1–2 week period between cycles for fixes, polish, and
  shaping the next round of pitches.
- **Scope**: a self-contained slice of a pitch. 3–7 per pitch. Tracked on the
  hill chart.
- **Hill chart**: per-scope status (`uphill | downhill | done`) for an active
  pitch, persisted as `specs/pitches/<id>/hill.json`.
- **Circuit breaker**: a pre-declared rule for what ships and what gets shelved
  if the appetite is exhausted.

## Success Criteria

1. US1 demonstrable: `/shape <topic>` produces a valid `pitch.md` that passes
   `validate-pitch.sh`.
2. US2 demonstrable: `/bet <pitch-id>` transitions a shaped pitch to `bet`
   with cycle set, and `validate-pitch.sh` still passes.
3. US3 demonstrable: `/cycle-start` creates a hill.json that conforms to
   `shared/templates/sdd/hill-chart.json` schema.
4. US7 verified: `validate-pitch.sh` is wired into `sync-check.yml` and fails
   CI on a deliberately broken pitch fixture.
5. US8 verified: existing `specs/<feature-id>/` dirs continue to pass
   `validate-spec.sh` after the extension.
6. FR-016 verified: `scope-executor.md` has no inlined build logic — it
   delegates to `build`.
7. No regressions: full existing test suite passes (`tests/test-*.sh`).
