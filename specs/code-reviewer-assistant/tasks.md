# Tasks: Code Reviewer Assistant

<!-- [US#] = traceability to spec.md user stories. [P] = parallelizable within phase. -->

## Phase 1: Fix Foundations & Provider Config

### [US8] Provider configuration redesign

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 1.1 | [P] Redesign `providers.toml` schema with typed providers (`cli`, `openai-compatible`, `ollama`, `custom`), defaults, and fallback chain sections [FR-038, FR-039, FR-040, FR-041, FR-042, FR-043] | `shared/templates/provider-profile-template.toml` | M | [ ] |
| 1.2 | [P] Create `openai-compatible.sh` provider adapter — curl-based chat completion, auth via `api_key_env` resolution, response extraction, error handling [FR-039, FR-040] | `scripts/provider-adapters/openai-compatible.sh` (new) | M | [ ] |
| 1.3 | [P] Create `ollama.sh` provider adapter — CLI for local (`ollama run`), HTTP API for remote (`curl`), `OLLAMA_HOST` override [FR-041] | `scripts/provider-adapters/ollama.sh` (new) | M | [ ] |
| 1.4 | Update `peer-review-runner.sh` with type-based dispatch (`case` on provider type → adapter or direct command), fallback chain walk on healthcheck failure [FR-042, FR-043] | `scripts/peer-review-runner.sh` | L | [ ] |
| 1.5 | Add `--configure-providers` interactive flow to setup.sh — type selection, field prompts per type, connection test, default-peer assignment [FR-044] | `scripts/setup.sh` | M | [ ] |
| 1.6 | [P] Fix tmux env-var propagation — ensure vars set via `tmux setenv` reach the running Claude process | `adapters/claude-code/claude-code` | S | [ ] |
| 1.7 | [P] Fix review banner timing — display after tmux attach, not before | `scripts/peer-review-runner.sh` | S | [ ] |

### [US9] Fallback chain and health checks

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 1.8 | Update `providers-health.sh` to handle typed providers and fallback chain diagnostics | `scripts/providers-health.sh` | S | [ ] |

### Phase 1 integration and testing

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 1.9 | Wire `collaboration-template.md` into `/phase-complete` flow (Phase 1 scope: template integration only; full command rewrite is task 2.27) | `adapters/claude-code/.claude/commands/phase-complete.md` | S | [ ] |
| 1.10 | Create `test-peer-review.sh` — runner unit tests: TOML parsing for all 4 types, provider dispatch, fallback chain engagement, healthcheck failure handling | `tests/test-peer-review.sh` (new) | M | [ ] |
| 1.11 | End-to-end smoke test: plan review with real provider (manual verification) | — | M | [ ] |

**Phase 1 exit criteria**: `./claude-code --peer-review gdx-spark ~/test-project` reaches a real LLM, produces a parseable verdict. Fallback chain engages when primary is unreachable.

---

## Phase 2: Review Loop, Handoff, & Enforcement

### [US1, US2] Agent-driven review loop

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 2.1 | Create `review-round-runner.sh` — one round per invocation: read `state.json`, snapshot working tree, spawn reviewer in sandbox, capture output, parse findings, write `findings-round-N.json`, update `state.json`, return verdict [FR-002, FR-003, FR-005] | `scripts/review-round-runner.sh` (new) | XL | [ ] |
| 2.2 | Create `/review-submit` command — validates clean worktree [US7, FR-035], checks breaker state, invokes `review-round-runner.sh`, returns verdict to agent [FR-001, FR-002] | `adapters/claude-code/.claude/commands/review-submit.md` (new) | M | [ ] |
| 2.3 | Create `review-loop.md` on-demand rule — documents agent-driven loop protocol, file contract, finding schema, disposition values, circuit breakers, commit lifecycle, plan-review product decision | `shared/rules/on-demand/review-loop.md` (new) | L | [ ] |

### [US6] Read-only enforcement

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 2.4 | Implement snapshot-copy sandbox in runner — macOS `cp -R` to temp dir, Linux bind mount or `cp -R`; isolate `.git`, block SSH/GPG forwarding; set `CCT_READ_ONLY=true` | `scripts/review-round-runner.sh` | L | [ ] |
| 2.5 | Implement post-review validation — compare real worktree and git log pre/post review; mark round INVALID and discard findings on violation [FR-008, FR-009] | `scripts/review-round-runner.sh` | M | [ ] |

### [US1, US2] Structured finding schema

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 2.6 | Implement finding parser — extract findings from reviewer free-text, generate stable IDs via SHA-256 of `(file + category + normalized_description)`, populate `line_hint` with semantic anchors [FR-010–FR-013] | `scripts/review-round-runner.sh` | L | [ ] |
| 2.7 | Implement resolution protocol — agent reads findings, writes `resolution-round-N.json` with dispositions (`fixed` + commit_ref, `disputed` + detail, `deferred`, `not-applicable`) [FR-014–FR-016] | Agent manifest + `review-loop.md` rule | M | [ ] |

### [US4, US5] Circuit breakers

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 2.8 | Implement round-counter breaker (`CCT_REVIEW_MAX_ROUNDS`, default 5) and wall-clock breaker (`CCT_REVIEW_TIMEOUT_SEC`, default 900) — all write `breaker-tripped.json` [FR-017, FR-018, FR-021, FR-022] | `scripts/review-round-runner.sh` | M | [ ] |
| 2.9 | Implement stale-finding breaker — detect same finding ID with `fixed` disposition across `CCT_REVIEW_STALE_THRESHOLD` consecutive rounds; do NOT auto-downgrade; escalate to human [FR-019, FR-020] | `scripts/review-round-runner.sh` | M | [ ] |
| 2.10 | Implement provider-unavailable breaker — fire when all fallback providers fail healthcheck [FR-023] | `scripts/review-round-runner.sh` | S | [ ] |

### [US12, US13] Human decision channel

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 2.11 | Create `/review-decide` command — accepts `approve|reject|retry`, writes `.cct/review/decision.json` [FR-024, FR-025, FR-029] | `adapters/claude-code/.claude/commands/review-decide.md` (new) | M | [ ] |
| 2.12 | Implement approve path — agent writes `loop-summary.json` with `bypass: true`, breaker type, unresolved findings [FR-026] | Agent manifest + runner | S | [ ] |
| 2.13 | Implement reject path — agent logs rejection, aborts [FR-027] | Agent manifest | S | [ ] |
| 2.14 | Implement retry path — increment `attempt` counter, reset breaker state (round-within-attempt, wall-clock, stale count), continue monotonic round numbering [FR-028] | `scripts/review-round-runner.sh` | M | [ ] |

### [US3] Commit-strategy modes

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 2.15 | Implement `--review-commits` flag parsing (`single`, `per-round`, `squash`) and propagation to runner [FR-030] | `adapters/claude-code/claude-code` | S | [ ] |
| 2.16 | Implement per-round commit format `fix(review): round N — <summary>` [FR-031, FR-036] | Agent manifest + `review-loop.md` | S | [ ] |
| 2.17 | Implement single-commit (amend) mode [FR-032, FR-036] | Agent manifest + `review-loop.md` | S | [ ] |
| 2.18 | Implement squash mode — per-round during loop; on PASS: `git reset --soft` to pre-review commit, present squash message for user approval via `phase-workflow.md` commit-approval step [FR-033, FR-036] | Agent manifest + runner | M | [ ] |
| 2.19 | Implement squash failure recovery — fall back to merge commit, go through commit-gate approval [FR-034] | Agent manifest | S | [ ] |
| 2.19a | Ensure commit strategies apply only to Build-phase review — plan review does not participate in fix loops or commit strategies [FR-037] | `review-loop.md` rule, agent manifests | S | [ ] |

### [US11] Stop hook and collaboration artifact

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 2.20 | Rewrite `peer-review-on-stop.sh` — validate `loop-summary.json` exists with PASS or approved bypass; plan-phase sessions exempt [FR-045] | `adapters/claude-code/.claude/hooks/peer-review-on-stop.sh` | M | [ ] |
| 2.21 | Implement `build-review.md` artifact generation — completing actor (runner on PASS, agent on bypass) writes to `specs/<feature-id>/collaboration/` with full frontmatter schema [FR-005a, FR-005b] | `scripts/review-round-runner.sh`, agent manifest | M | [ ] |
| 2.22 | [US10] Implement plan-consult path — single advisory round, writes `plan-consult.md` with `mode: consult`, no loop metadata [FR-005c] | `scripts/review-round-runner.sh`, agent manifest | S | [ ] |

### Agent manifest updates

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 2.23 | Update Build agent manifest — after work: run `/review-submit`; on FAIL: read findings, address, write resolution, commit, resubmit; on breaker: print context, stop for human; **on `/review-decide retry`**: read `decision.json`, re-run `/review-submit` (agent is loop driver) [FR-001, FR-004, FR-028] | `adapters/claude-code/.claude/agents/build.md` | M | [ ] |
| 2.24 | Update Plan agent manifest — single advisory `/review-submit`, no fix loop (product decision) | `adapters/claude-code/.claude/agents/plan.md` | S | [ ] |
| 2.25 | Add launcher flags: `--review-commits`, `--review-max-rounds` | `adapters/claude-code/claude-code` | S | [ ] |
| 2.27 | Rewrite `/phase-complete` command — remove legacy pending-marker creation and stop-hook-triggers-review language; update instructions to assume review loop has already completed (agent-driven); validate `loop-summary.json` presence before proceeding; retain existing commit-gate approval step (used by squash mode FR-033) | `adapters/claude-code/.claude/commands/phase-complete.md` | M | [ ] |

### Phase 2 testing

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 2.26 | Create `test-review-loop.sh` — comprehensive loop tests with mock provider: round trips, finding ID stability across line-shifting edits, stale-finding escalation (not auto-accept), breaker escalation via `/review-decide`, read-only violation detection, commit-strategy correctness, dirty-worktree rejection, stop-hook validation-only, monotonic round numbering across retry attempts | `tests/test-review-loop.sh` (new) | XL | [ ] |

**Phase 2 exit criteria**: 2-round FAIL→fix→PASS loop with squash. Reviewer in snapshot copy. Circuit breaker fires at round 5, escalates to human. Stale findings remain blocking. Finding IDs stable across line shifts. Dirty worktree rejected. Stop hook validates (does not initiate). Monotonic rounds on retry.

---

## Phase 3: CI Gate & Governance

### [US11] CI validation

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 3.1 | Implement `validate-collaboration.sh` — Build review: PASS or approved bypass required; Plan review: advisory (warn, don't block); bypass without logged breaker type + decision fails [FR-046, FR-047] | `scripts/validate-collaboration.sh` (new) | M | [ ] |
| 3.2 | Add CI workflow step for collaboration validation | `.github/workflows/` | S | [ ] |

### Documentation and rule updates

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 3.3 | Update `provider-collaboration-protocol.md` with agent-driven loop semantics, typed providers, plan-review advisory carve-out | `shared/rules/on-demand/provider-collaboration-protocol.md` | M | [ ] |
| 3.3a | Update `phase-workflow.md` — remove language that `/phase-complete` triggers peer review via stop hook; document that review loop completes *before* `/phase-complete`; update commit-gate section to reference squash-approval flow | `shared/rules/on-demand/phase-workflow.md` | M | [ ] |
| 3.3b | Update `spec-workflow.md` — remove or revise any references to legacy stop-hook collaboration gating; align with advisory plan-review product decision | `shared/rules/on-demand/spec-workflow.md` | S | [ ] |
| 3.3c | Update `agent-team-protocol.md` — replace legacy collaboration gate (`/phase-complete` triggers peer review, `plan-consult.md` must PASS before Build, `build-review.md` must PASS before Review) with agent-driven semantics: review loop completes before `/phase-complete`, plan-consult FAIL is advisory, build-review requires PASS or approved bypass | `shared/rules/on-demand/agent-team-protocol.md` | M | [ ] |
| 3.4 | Add bypass audit trail metadata (`bypass: true`, `breaker: <type>`) to `loop-summary.json` schema | `scripts/review-round-runner.sh` | S | [ ] |
| 3.5 | Write "Getting Started with Code Reviewer Assistant" guide | `shared/docs/code-reviewer-assistant-guide.md` (new) | M | [ ] |

**Phase 3 exit criteria**: PR with missing/FAIL Build-phase review rejected by CI. Plan-phase FAIL logged as advisory. Bypass events auditable.

---

## Phase 4: Multi-Adapter & Polish

### [US5-adapter] Adapter expansion

| # | Task | File(s) | Est. | Done |
|---|------|---------|------|------|
| 4.1 | [P] Generate advisory peer-review content for Cursor, Copilot, Windsurf, Aider adapters [FR-050] | `scripts/generate.sh`, adapter configs | M | [ ] |
| 4.2 | [P] Add Codex adapter native peer-review support | `adapters/codex/` | M | [ ] |
| 4.3 | Add review scope filtering (code-only, design-only, security-focused) | rule + `review-round-runner.sh` | S | [ ] |
| 4.4 | Update all existing tests to pass with new components [FR-048] | `tests/test-shared-structure.sh`, `tests/test-generate.sh` | M | [ ] |

**Phase 4 exit criteria**: `generate.sh` propagates review-loop protocol to all adapters. Codex can act as both primary and reviewer.

---

## Final Verification

- [ ] All 834+ existing tests pass [FR-048]
- [ ] `generate.sh` exits cleanly and propagates `review-loop.md` to all 6 adapters [FR-050]
- [ ] Codex AGENTS.md output under 32 KiB [FR-049]
- [ ] End-to-end pilot: Build → review (2 rounds) → squash → commit with at least 2 provider combinations
- [ ] Circuit breaker pilot: round-limit trip → `/review-decide approve` → session continues
- [ ] Plan review pilot: advisory single-round, FAIL does not gate Build
