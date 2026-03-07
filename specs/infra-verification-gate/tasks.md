---
feature_id: infra-verification-gate
status: draft
date: 2026-03-07
---

# Tasks: Infrastructure Verification Gate

## [US1, US2, US3, US4, US6] Task 1: Create infra-verification.md rule

- [ ] Create `shared/rules/on-demand/infra-verification.md`
- [ ] Define verification commands for Docker, Compose, CI workflows
- [ ] Define environment failure protocol ("never skip" principle)
- [ ] Define health probe requirements (no business endpoints)
- [ ] Include example verification sequences
- **Owner**: Rules agent
- **Files**: `shared/rules/on-demand/infra-verification.md`

## [US1, US2, US5] Task 2: Update phase-workflow.md

- [ ] Add "Infrastructure Verification" step (2.5) to Post-Phase Steps
- [ ] Add infra verification items to Phase N Checklist
- [ ] Verify existing steps unchanged
- **Owner**: Rules agent
- **Files**: `shared/rules/on-demand/phase-workflow.md`

## [US6] Task 3: Update integration-testing.md

- [ ] Add "Demo / Example Application Verification" section
- [ ] Include empty stub detection guidance
- [ ] Verify existing sections unchanged
- **Owner**: Integration-testing agent
- **Files**: `claude_code/.claude/rules-library/integration-testing.md`

## [US1, US2, US4, US6] Task 4: Update Build agent manifest

- [ ] Add infrastructure verification to "What to Do" workflow (step 6.5)
- [ ] Add infra items to "Verification After Each Agent" checklist
- [ ] Add "Infrastructure Failure Protocol" section
- [ ] Verify existing steps unchanged
- **Owner**: Agent-manifest agent
- **Files**: `adapters/claude-code/.claude/agents/build.md`

## [US1, US2, US3, US5] Task 5: Update verify-on-stop.sh hook [P]

- [ ] Add git diff detection for infrastructure files
- [ ] Add Docker build verification
- [ ] Add Docker Compose up/health/down verification
- [ ] Add CI workflow YAML validation
- [ ] Add Docker-not-installed graceful skip
- [ ] Add timeout wrapper for Docker commands
- [ ] Add trap for compose cleanup on failure
- [ ] Verify zero overhead when no infra files changed
- **Owner**: Hook agent
- **Files**: `claude_code/.claude/hooks/verify-on-stop.sh`

## [US7] Task 5b: Add shell script verification to verify-on-stop.sh [P]

- [ ] Add git diff detection for modified `.sh` scripts
- [ ] Add `bash -n` syntax check for each modified script
- [ ] Add safe smoke invocation for scripts with `--help` support
- [ ] Verify zero overhead when no `.sh` files changed
- **Owner**: Hook agent
- **Files**: `claude_code/.claude/hooks/verify-on-stop.sh`
- **Note**: This extends Task 5 — same file, same owner. Can be implemented as part of Task 5.

## [All] Task 6: Update generate.sh [P]

- [ ] Add `infra-verification.md` to on-demand rule propagation
- [ ] Verify all 6 adapters receive the content
- [ ] Verify Codex AGENTS.md stays under 32 KiB
- **Owner**: Pipeline agent
- **Files**: `scripts/generate.sh`

## [All] Task 7: Verification

- [ ] `bash scripts/generate.sh` — clean exit
- [ ] `git diff adapters/` — expected changes only
- [ ] `bash tests/test-shared-structure.sh` — all pass
- [ ] `bash tests/test-generate.sh` — all pass
- [ ] `bash tests/test-hooks.sh` — all pass
- [ ] `bash scripts/validate-spec.sh --feature-id infra-verification-gate` — passes
- [ ] 834+ existing tests green
- [ ] Manual pilot: create Dockerfile → hook detects → runs docker build → reports result

---

**Parallelism notes:**
- Tasks 1–2 (Rules agent) are sequential — Task 2 references Task 1
- Tasks 3, 4, 5, 6 are independent and can run in parallel [P]
- Task 7 runs after all others complete
