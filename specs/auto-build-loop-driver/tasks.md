# Tasks: auto-build-loop driver core (advisory profile)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: CLI, preflight, ledger scaffolding

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Driver skeleton: arg parsing (FR-1), profile guard (advisory only), env overrides (CCT_CLAUDE_BIN, CCT_AUTOBUILD_DIR), exit-code contract | `scripts/auto-build-loop.sh` | build | [ ] |
| 2 | | Preflight chain (FR-2): tools, spec approved, validate-spec, origin gate, targeted provider health, clean worktree, then base-ref resolve → feature-branch create/checkout → master/main refusal | `scripts/auto-build-loop.sh` | build | [ ] |
| 2a | | `--provider <name>` mode in providers-health.sh: check named provider + its fallback chain only (FR-2a); existing no-arg behavior unchanged | `scripts/providers-health.sh` | build | [ ] |
| 3 | | Config loader + snapshot + ledger init + events.jsonl journaling (FR-3); automation.json template | `scripts/auto-build-loop.sh`, `shared/templates/sdd/automation-template.json` | build | [ ] |
| 4 | [P] | Test harness scaffolding: mock claude, mock reviewer profiles, setup helpers; US1 assertions (preflight rejections, profile guard, ledger init) | `tests/test-auto-build-loop.sh` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] `bash -n scripts/auto-build-loop.sh` clean; Bash 3.2 constructs only
- [ ] US1 assertions green (dirty worktree, missing approval, non-advisory profile, origin >= 2 all refuse)

---

## US2: Phase enumeration + build/test/commit loop

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | | Phase enumeration from tasks.md US-groups + config override + milestone markers (FR-4) | `scripts/auto-build-loop.sh` | build | [ ] |
| 6 | | Phase prompt composer (US group + FRs + no-commit contract) and headless session runner with result-JSON parsing, one max-turns continuation, cost/wall-clock caps (FR-5, FR-6) | `scripts/auto-build-loop.sh` | build | [ ] |
| 7 | | Test runner + bounded fix sessions (FR-7); driver-owned phase commits + master/main refusal + empty-diff park (FR-8) | `scripts/auto-build-loop.sh` | build | [ ] |
| 8 | [P] | US2 assertions: happy-path phase (mock claude writes files, canned success JSON), cost-cap park, max-turns continuation-then-park, empty-diff park | `tests/test-auto-build-loop.sh` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] Single-phase run against mock claude produces exactly one `[auto-build]` commit and journaled transitions
- [ ] Cap assertions green

---

## US3: Review-round integration + hard gate

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 9 | | Review state init + runner invocation with CCT_REVIEW_BASE_REF (FR-9); gating-reviewer selection from reviewers list (FR-12) | `scripts/auto-build-loop.sh` | build | [ ] |
| 10 | | FAIL path: fix session, driver commit, commit_ref injection into dispositions, re-invoke; BREAKER park (FR-10) | `scripts/auto-build-loop.sh` | build | [ ] |
| 11 | | PASS hard gate + review archive/reset per phase (FR-11) | `scripts/auto-build-loop.sh` | build | [ ] |
| 12 | [P] | US3 assertions: FAIL→fix→PASS with commit_ref present, breaker → exit 4 + esc record, forged-summary mismatch parks, archive exists per phase | `tests/test-auto-build-loop.sh` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] Two-round FAIL→PASS run green end-to-end with mock reviewer profiles
- [ ] Runner state fully reset between phases (fresh loop_start, round 1)

---

## US4: Origin re-check, milestones, parking, dry-run

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 13 | | Post-review origin re-check + artifact/summary commit (FR-13) | `scripts/auto-build-loop.sh` | build | [ ] |
| 14 | | Milestone checkpoint write + exit 3 + approved-by resume; escalation records on every park (FR-14, FR-15) | `scripts/auto-build-loop.sh` | build | [ ] |
| 15 | | --dry-run planner (FR-16); resume idempotency (re-derive commits/archives, skip done side effects) | `scripts/auto-build-loop.sh` | build | [ ] |
| 16 | [P] | US4 assertions: milestone pause/sign-off/resume, origin-partial park, dry-run zero side effects, kill-after-commit resume no duplicate | `tests/test-auto-build-loop.sh` | build | [ ] |

**Checkpoint US4** — verify before continuing:
- [ ] Full 2-phase advisory run: exit 3 at milestone, resume to done, nothing pushed, no gh invoked
- [ ] All park paths produce esc-<n>.json and exit 4

---

## US5: Docs, skills, command, CI wiring

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 17 | | auto-build-loop skill (protocol, gate map, ledger schema, resume playbook) | `shared/skills/auto-build-loop/SKILL.md` | build | [ ] |
| 18 | | Autonomy Profiles section + driver-as-submitter notes; regenerate adapters | `shared/skills/phase-workflow/SKILL.md`, `shared/skills/agent-team-protocol/SKILL.md`, `shared/skills/review-loop/SKILL.md`, `adapters/` (generated) | build | [ ] |
| 19 | [P] | /auto-build scaffolding command (FR-19) | `adapters/claude-code/.claude/commands/auto-build.md` | build | [ ] |
| 20 | [P] | settings.json env keys; test-counts registration; sync-check.yml run + bash -n steps | `adapters/claude-code/.claude/settings.json`, `tests/test-counts.env`, `.github/workflows/sync-check.yml` | build | [ ] |

**Checkpoint US5** — verify before continuing:
- [ ] `bash scripts/generate.sh` produces zero drift
- [ ] Full local suite pass: test-auto-build-loop, test-review-loop, test-shared-structure (repo assertions), validate-spec --all

---

## Final Verification

- [ ] Linter/syntax: `bash -n` on driver + all touched scripts, 0 errors
- [ ] All existing tests pass (counts in tests/test-counts.env updated)
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] End-to-end toy run per specs/auto-build-loop/design.md §9 (advisory, mock claude + mock reviewer) executed and results recorded in automation-summary of the toy spec
- [ ] Origin alignment re-checked (Gate 3) before /phase-complete
