# Tasks: Shape-Up methodology support

<!-- Source of truth for sub-issues filed against epic #13. -->
<!-- Each US group below maps to one sub-issue. [P] = parallelizable within a group. -->

## US1 + US7 (S1): Foundation — templates, dogfood pitch, validator

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | [P] | Write pitch template | `shared/templates/sdd/pitch-template.md` | Templates | [x] |
| 2 | [P] | Write hill chart JSON schema | `shared/templates/sdd/hill-chart.json` | Templates | [x] |
| 3 | [P] | Write cycle-retro template | `shared/templates/sdd/cycle-retro-template.md` | Templates | [x] |
| 4 | [P] | Write cooldown-report template | `shared/templates/sdd/cooldown-report-template.md` | Templates | [x] |
| 5 |    | Write dogfood pitch using new template | `specs/pitches/0001-shape-up-support/pitch.md` | Pitch dogfood | [x] |
| 6 | [P] | Write SDD plan for the pitch | `specs/pitches/0001-shape-up-support/plan.md` | Pitch dogfood | [x] |
| 7 | [P] | Write SDD spec for the pitch | `specs/pitches/0001-shape-up-support/spec.md` | Pitch dogfood | [x] |
| 8 | [P] | Write SDD tasks for the pitch | `specs/pitches/0001-shape-up-support/tasks.md` | Pitch dogfood | [x] |
| 9 |    | Write `validate-pitch.sh` | `scripts/validate-pitch.sh` | Validator | [x] |
| 10 |   | Run validator against dogfood pitch | (run) | Validator | [x] |

**Checkpoint S1** — verify before continuing:
- [x] `bash -n scripts/validate-pitch.sh` passes
- [x] `scripts/validate-pitch.sh --all` exits 0
- [x] `scripts/validate-pitch.sh --pitch-id 0001-shape-up-support` exits 0
- [x] All four templates present under `shared/templates/sdd/`

---

## US1 + US2 (S2): Shaping & betting — `pitch-shaper`, `/shape`, `/bet`

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 11 |    | Write `pitch-shaper` agent | `shared/agents/pitch-shaper.md` | Agents-shaping | [ ] |
| 12 | [P] | Write `/shape` command | `shared/commands/shape.md` | Agents-shaping | [ ] |
| 13 | [P] | Write `/bet` command (sets `bet_status: bet`, `cycle`, appends bet log) | `shared/commands/bet.md` | Agents-shaping | [ ] |
| 14 |    | Run `scripts/generate.sh` and verify adapter outputs | `adapters/**/` | Pipeline | [ ] |

**Checkpoint S2** — verify before continuing:
- [ ] `/shape` produces a pitch that passes `validate-pitch.sh`
- [ ] `/bet` transitions a pitch's `bet_status` from `shaped` → `bet` with `cycle` populated
- [ ] `generate.sh` runs clean and adapter diffs include shape/bet content

---

## US3 + US4 (S3): Cycle execution — `scope-executor`, `/cycle-start`, `/hill`

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 15 |    | Write `scope-executor` agent (thin adapter on `build`) | `shared/agents/scope-executor.md` | Agents-execution | [ ] |
| 16 | [P] | Write `/cycle-start` command (creates hill.json, sets `bet_status: building`) | `shared/commands/cycle-start.md` | Agents-execution | [ ] |
| 17 | [P] | Write `/hill` command (`/hill <scope> <up\|down\|done>`) | `shared/commands/hill.md` | Agents-execution | [ ] |
| 18 |    | Run `scripts/generate.sh` and verify adapter outputs | `adapters/**/` | Pipeline | [ ] |

**Checkpoint S3** — verify before continuing:
- [ ] `scope-executor.md` contains no inlined `build` logic — delegation only
- [ ] `/cycle-start` produces a `hill.json` matching the JSON schema
- [ ] `/hill S1 down` updates the right scope's status and `last_updated`

---

## US5 + US6 (S4): Closing the loop — `cycle-retro`, `cooldown-report`, `/cooldown`

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 19 |    | Write `cycle-retro` agent | `shared/agents/cycle-retro.md` | Agents-closing | [ ] |
| 20 | [P] | Write `cooldown-report` agent | `shared/agents/cooldown-report.md` | Agents-closing | [ ] |
| 21 | [P] | Write `/cooldown` command | `shared/commands/cooldown.md` | Agents-closing | [ ] |
| 22 |    | Run `scripts/generate.sh` and verify adapter outputs | `adapters/**/` | Pipeline | [ ] |

**Checkpoint S4** — verify before continuing:
- [ ] `cycle-retro` parses `pitch.md` + `hill.json` + `git log` and produces a `cycle-NN.md`
- [ ] `cooldown-report` produces a report listing recommended bets for next cycle
- [ ] `/cooldown` sets active pitch's `bet_status` to `shipped` or `shelved`

**Circuit breaker reminder**: if S4 is uphill at week 4, ship S1+S2+S3+S5 and shelve S4.

---

## US7 + US8 (S5): CI wiring + docs

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 23 |    | Extend `validate-spec.sh` to walk `specs/pitches/*/` (additive) | `scripts/validate-spec.sh` | CI+docs | [ ] |
| 24 | [P] | Wire `validate-pitch.sh` into `sync-check.yml` (gated on `specs/pitches/`) | `.github/workflows/sync-check.yml` | CI+docs | [ ] |
| 25 | [P] | Add tests for validate-pitch | `tests/test-validate-pitch.sh` | CI+docs | [ ] |
| 26 | [P] | Write methodology doc | `docs/shape-up-workflow.md` | CI+docs | [ ] |
| 27 | [P] | Update README scorecard for Shape-Up coverage | `README.md` | CI+docs | [ ] |

**Checkpoint S5** — verify before continuing:
- [ ] `bash -n scripts/validate-spec.sh` passes after extension
- [ ] `validate-spec.sh --all` validates both top-level and nested specs
- [ ] `tests/test-validate-pitch.sh` covers happy path + each failure mode (invalid appetite, invalid bet_status, missing circuit_breaker, missing cycle when bet)
- [ ] `sync-check.yml` runs validate-pitch only when `specs/pitches/` exists
- [ ] README scorecard mentions Shape-Up coverage

---

## Final Verification

- [ ] `bash scripts/validate-pitch.sh --all` exits 0
- [ ] `bash scripts/validate-spec.sh --all` exits 0 (existing + nested)
- [ ] `bash scripts/generate.sh` runs clean
- [ ] `git diff --exit-code adapters/` shows expected changes only
- [ ] `tests/test-*.sh` all pass
- [ ] No `[NEEDS CLARIFICATION]` markers remain in `spec.md`
- [ ] All five sub-issues filed against epic #13
- [ ] `docs/shape-up-workflow.md` exists and links from README
