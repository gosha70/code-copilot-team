# Shape-Up Workflow

Shape-Up is Basecamp's product development methodology. Code Copilot Team ships a
local-first implementation: pitches, cycles, hill charts, and circuit breakers,
all as plain files under `specs/pitches/<id>/`. The four agents and five slash
commands documented below drive the workflow end-to-end.

## When to use Shape-Up vs. SDD only

Code Copilot Team ships two complementary planning layers:

| Layer | Answers | Artifacts |
|---|---|---|
| **SDD** | "How do we know we built the right thing?" | `plan.md`, `spec.md`, `tasks.md` |
| **Shape-Up** | "What do we build next, and how big should it be?" | `pitch.md`, `hill.json`, retros |

Use **SDD alone** for feature-shaped work where the requirement is clear and the
question is execution rigor. Bug fixes, well-scoped features, refactors.

Use **Shape-Up + SDD** for product-shaped work where the question is *what to
build*. Greenfield product development, ambiguous problem space, multiple
possible solutions, time-boxed bets. The pitch describes the *bet*; SDD's
plan/spec/tasks describe the *implementation* underneath one or more scopes of
that pitch.

The two coexist by nesting: `specs/pitches/<id>/` holds `pitch.md` (Shape-Up)
*plus* `plan.md`/`spec.md`/`tasks.md` (SDD) *plus* `hill.json` (per-scope status).

## Key concepts

- **Pitch** — a shaped problem + rough solution + appetite. Persisted as
  `specs/pitches/<NNNN-slug>/pitch.md`.
- **Appetite** — fixed time budget. One of `2w`, `4w`, `6w`. Scope flexes,
  time doesn't.
- **Bet** — a pitch chosen for the next cycle. Reflected by
  `bet_status: bet` and a populated `cycle:` field.
- **Cycle** — uninterrupted build period at the appetite. Identified by a
  cycle number (e.g. `01`).
- **Cooldown** — 1–2 weeks between cycles for fixes, polish, and shaping the
  next round of pitches.
- **Scope** — self-contained slice of a pitch. 3–7 per pitch. Tracked on
  the hill chart.
- **Hill chart** — per-scope status (`uphill | downhill | done`) for an
  active pitch, persisted as `specs/pitches/<id>/hill.json`.
- **Circuit breaker** — pre-declared rule for what ships and what gets
  shelved if the appetite is exhausted.

## Directory layout

```
specs/
├── pitches/
│   ├── 0001-foo/
│   │   ├── pitch.md         (Shape-Up — appetite, scopes, no-gos, rabbit holes)
│   │   ├── plan.md          (SDD)
│   │   ├── spec.md          (SDD)
│   │   ├── tasks.md         (SDD)
│   │   └── hill.json        (per-scope status: uphill | downhill | done)
│   └── 0002-bar/...
└── retros/
    ├── cycle-01.md
    └── cooldown-after-01.md
```

## Pitch lifecycle (`bet_status`)

```
shaping → shaped → bet → building → shipped
                                  ↘ shelved
```

| status | Meaning | How to advance |
|---|---|---|
| `shaping` | Draft — not yet ready for the betting table | `pitch-shaper` agent populates fields and sets `shaped` |
| `shaped` | Ready for the betting table | `/bet <pitch-id>` after the betting decision |
| `bet` | Committed to the next cycle, no scopes started | `/cycle-start <pitch-id>` initializes hill.json |
| `building` | Cycle in progress | `/cooldown` decides ship vs. shelve |
| `shipped` | Cycle closed successfully | terminal |
| `shelved` | Cycle closed without shipping | terminal |

## Workflow at a glance

```
   /shape <topic>           — invokes pitch-shaper to draft a pitch
       │
       ▼
   pitch.md (bet_status: shaped)
       │
   /bet <pitch-id>          — locks for next cycle, sets cycle: NN
       │
       ▼
   pitch.md (bet_status: bet, cycle: NN)
       │
   /cycle-start <pitch-id>  — creates hill.json, all scopes = uphill
       │
       ▼
   pitch.md (bet_status: building) + hill.json
       │
   For each scope:
     scope-executor          — reads pitch context, transitions uphill→downhill,
                               delegates implementation to the build agent
     /hill <scope> done      — human verification gate, marks scope complete
       │
       ▼ (after all scopes done OR appetite exhausted)
   /cooldown                — invokes cooldown-report,
                              transitions building → shipped or shelved
       │
       ▼
   pitch.md (terminal) + specs/retros/cooldown-after-NN.md
```

End-of-cycle the `cycle-retro` agent generates `specs/retros/cycle-NN.md`.

## Frontmatter schema

`pitch.md` frontmatter — enforced by `scripts/validate-pitch.sh`:

```yaml
---
pitch_id: 0001-shape-up-support       # must match directory name
title: "Add Shape-Up methodology support"
appetite: 6w                          # one of: 2w | 4w | 6w
bet_status: shaping                   # one of: shaping | shaped | bet |
                                      #         building | shipped | shelved
cycle: ""                             # required when bet_status >= bet
circuit_breaker: "..."                # required when bet_status >= shaped
shaped_by: "author"
shaped_date: 2026-05-02
---
```

Validation rules (see `scripts/validate-pitch.sh`):

- `appetite` must be `2w`, `4w`, or `6w`.
- `bet_status` must be one of the six lifecycle values.
- `cycle` must be non-empty when `bet_status` is `bet`, `building`, or `shipped`.
- `circuit_breaker` must be non-empty when `bet_status` is `shaped` or later.
- `pitch_id` must equal the directory name.
- `title`, `shaped_by`, `shaped_date` are always required.

## Agents

| Agent | Triggered by | What it does |
|---|---|---|
| `pitch-shaper` | `/shape` | Asks clarifying questions, produces a 3–7-scope pitch with appetite and circuit breaker. Sets `bet_status: shaped`. |
| `scope-executor` | (manual or `/cycle-start` follow-up) | Reads pitch + hill.json, transitions a scope `uphill → downhill`, delegates implementation to the existing `build` agent. Thin adapter — no inlined build logic. |
| `cycle-retro` | end of cycle | Parses `pitch.md`, `hill.json`, and `git log` to produce `specs/retros/cycle-NN.md`. Empty-case stub if no bets ran. |
| `cooldown-report` | `/cooldown` | Summarizes bug fixes from `git log` + lists pitches shaped during cooldown. Recommends candidates for the next betting table. Writes `specs/retros/cooldown-after-NN.md`. |

## Slash commands

| Command | Effect |
|---|---|
| `/shape <topic>` | Invokes `pitch-shaper`. New pitch ID, frontmatter populated, `bet_status: shaped`. |
| `/bet <pitch-id>` | Transitions `shaped → bet`. Sets `cycle: NN` (next free). Validates. |
| `/cycle-start <pitch-id>` | Creates `hill.json` (all scopes `uphill`). Transitions `bet → building`. Validates. |
| `/hill <scope> <up\|down\|done> [--force]` | Updates a scope's status. Transition guard: `done → uphill` requires `--force`. |
| `/cooldown` | Invokes `cooldown-report`. If a pitch is `building`, asks the user to choose `shipped` or `shelved` and updates frontmatter. Validates. |

## Install surface

After `setup.sh --sync` (Claude Code adapter), the runtime files live under
`~/.claude/`:

- `~/.claude/agents/{pitch-shaper,scope-executor,cycle-retro,cooldown-report}.md`
- `~/.claude/commands/{shape,bet,cycle-start,hill,cooldown}.md`
- `~/.claude/templates/sdd/{pitch,cycle-retro,cooldown-report}-template.md`
- `~/.claude/templates/sdd/hill-chart.json`
- `~/.claude/templates/sdd/validate-pitch.sh` (consumer-side validator)

The canonical validator at `scripts/validate-pitch.sh` is location-aware: it
prefers `$VALIDATE_PITCH_REPO`, falls back to the script's parent dir if it
contains `specs/`, then to `$PWD`. CI uses the canonical copy; consumer projects
use `~/.claude/templates/sdd/validate-pitch.sh` invoked from project root.

## CI integration

`.github/workflows/sync-check.yml` runs `validate-pitch.sh --all` whenever
`specs/pitches/` exists in the repo. The job is gated:

```yaml
- name: Validate Shape-Up pitch conformance
  run: |
    if [[ -d specs/pitches/ ]] && ls specs/pitches/*/pitch.md >/dev/null 2>&1; then
      bash scripts/validate-pitch.sh --all
    else
      echo "No Shape-Up pitches found; skipping pitch validation"
    fi
```

`scripts/validate-spec.sh --all` was extended to also walk `specs/pitches/*/`
so SDD artifacts nested under pitches (`plan.md`, `spec.md`, `tasks.md`) are
validated alongside top-level specs. The existing `specs/<feature-id>/` walk
is unchanged — extension is strictly additive.

## Worked example

The first dogfood pitch is `specs/pitches/0001-shape-up-support/` — the bet
to add Shape-Up support to `code-copilot-team` itself. See its `pitch.md`,
`plan.md`, `spec.md`, and `tasks.md` for a complete worked example using this
layout, including ADRs (nested layout, `scope-executor` as adapter not fork,
disjoint frontmatter namespaces), 17 functional requirements, and a 5-scope
breakdown with file ownership.

## What's not included in v1

- No multi-person bets, distributed betting tables, or async vote tooling.
  Solo / small-team only.
- No hill-chart visualization beyond the JSON file. Terminal/IDE rendering is
  a future enhancement.
- No external tracker integration (Linear, GitHub Projects). Local-first.
- No automated appetite or circuit-breaker enforcement — circuit breakers are
  social, not automated. The methodology depends on the team honoring the
  pre-declared rule.
