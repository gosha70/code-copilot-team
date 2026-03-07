# Claude Code Session Kickoff — Infrastructure Verification Gate

## How to Use This

Start Claude Code in the `code-copilot-team` repo root, then paste the
appropriate prompt below for each phase. Run one phase per session.

---

## Phase 1: Plan (ALREADY DONE)

The spec, plan, and tasks are pre-written in `specs/infra-verification-gate/`.
Skip straight to Build.

---

## Phase 2: Build

Start a new Claude Code session (`claude` from repo root), then paste this
prompt directly:

```
Implement the Infrastructure Verification Gate per the approved spec and plan in specs/infra-verification-gate/.

Read these files first:
1. specs/infra-verification-gate/plan.md — full implementation plan with 7 tasks and file ownership
2. specs/infra-verification-gate/spec.md — requirements FR-001 through FR-013
3. specs/infra-verification-gate/tasks.md — task decomposition with parallelism markers

Context — why this exists:
A real ai-atlas Build session committed Docker support (Dockerfile + docker-compose.yml) after three
untested revisions. The agent never ran `docker compose up --build`. When it failed on the user's
machine, the agent suggested skipping Docker instead of fixing it. A second incident in Sprint 2 of
the code-copilot-team repo itself repeated the same pattern with shell scripts (launcher flags, hooks)
— the agent suggested skipping the banner visibility test. This spec closes both quality gates.

Key constraints:
- Shared rule changes go through shared/ → generate.sh → adapters/
- Agent manifest (build.md) is Claude Code adapter-specific — edit directly
- Hook changes go in claude_code/.claude/hooks/verify-on-stop.sh
- Do NOT modify shared/rules/always/* or shared/templates/sdd/*
- Run the full test suite (834+ tests) after all changes
- Show the delegation plan before executing

The plan has 7 tasks (plus Task 5b from the Sprint 2 addendum). Tasks 3, 4, 5/5b, 6 can run in parallel (non-overlapping file ownership).

Note: The spec now includes FR-014 through FR-018 (Sprint 2 Addendum) for executable shell script
verification. Task 5b adds `bash -n` syntax checking for modified .sh files to the hook.
```

---

## Phase 3: Review

Start a new Claude Code session (`claude` from repo root), then paste this
prompt directly:

```
Review all changes from the Infrastructure Verification Gate build.

Check against:
1. specs/infra-verification-gate/spec.md — verify FR-001 through FR-013 are implemented
2. specs/infra-verification-gate/plan.md — verify all acceptance criteria checkboxes are satisfiable

Specific things to verify:
- infra-verification.md rule exists in shared/rules/on-demand/ and defines Docker, Compose, CI workflow verification
- phase-workflow.md has the new Infrastructure Verification step (2.5) and updated Phase N checklist
- build.md agent manifest has Infrastructure Failure Protocol and infra verification in the per-agent checklist
- verify-on-stop.sh detects infra files via git diff, runs Docker/Compose/workflow checks, skips when no infra files changed
- verify-on-stop.sh gracefully handles missing Docker (skip, not fail)
- verify-on-stop.sh uses timeout and trap for compose cleanup
- generate.sh propagates infra-verification.md to all 6 adapters
- Codex AGENTS.md stays under 32 KiB
- All 834+ existing tests pass
- No files outside the spec scope were modified

Additionally, test the hook manually:
1. In a test project with a Dockerfile, run: echo '{}' | bash claude_code/.claude/hooks/verify-on-stop.sh
2. Verify it detects the Dockerfile and attempts docker build
3. In a test project without Docker files, verify the hook exits immediately (zero overhead)
```

---

## Phase 4: Commit

After review passes:

```
Commit all Infrastructure Verification Gate changes with message:

feat(quality): add infrastructure verification gate — Docker, Compose, CI workflow checks

Closes the quality gate gap where infrastructure artifacts (Dockerfiles, compose files, CI
workflows) were committed without being executed. Changes:
- Add shared/rules/on-demand/infra-verification.md with "build it, run it" principle
- Update phase-workflow.md with Infrastructure Verification step and Phase N checklist items
- Update integration-testing.md with Demo Application Verification section
- Update Build agent manifest with infra verification workflow and failure protocol
- Update verify-on-stop.sh hook to detect and verify infra files via git diff
- Update generate.sh to propagate infra-verification rule to all 6 adapters

Refs: specs/infra-verification-gate/spec.md
```

---

## Notes

- This feature was motivated by a real failure in the ai-atlas project where Docker support
  was committed untested. The full failure analysis is in the spec's Problem Statement.
- The hook uses the existing `HOOK_STOP_BLOCK` convention — by default it reports failures
  without blocking (exit 0). Set `HOOK_STOP_BLOCK=true` for enforcement.
- Machines without Docker installed get a graceful skip, not a hard failure.
- Non-Claude adapters receive the `infra-verification.md` rule as advisory content only
  (consistent with SDD Sprint 1 pattern).
