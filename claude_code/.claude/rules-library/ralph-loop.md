# Ralph Loop (Single-Agent Autonomous Loop)

A single agent runs in a loop until the task is complete. Each iteration reads a plan, picks the next incomplete item, implements it, runs tests, and commits if passing.

## When to Use Ralph Loop vs Team Workflow

| Factor | Ralph Loop | Team Workflow |
|--------|-----------|---------------|
| Task scope | Single-domain, well-defined | Multi-domain, cross-cutting |
| Completion criteria | Verifiable by tests | Requires human judgment |
| Codebase familiarity | Greenfield or well-understood | Unfamiliar or complex |
| Design decisions needed | Few or none (plan is locked) | Many, iterative |
| Parallelism benefit | Low (sequential work) | High (independent domains) |
| Test suite | Exists and reliable | Missing or incomplete |

**Use Ralph Loop when:**
- The task has clear, testable completion criteria
- A plan is already approved and doesn't need human decisions mid-flight
- Work is sequential (each step depends on the previous)
- You expect 3+ iterations to reach completion

**Use Team Workflow when:**
- Multiple independent domains can be worked in parallel
- The task requires human design decisions during implementation
- There's no automated test suite to verify progress
- The work spans unrelated parts of the codebase

## How It Works

1. **PRD file** — A structured plan with user stories, each marked pass/fail
2. **Progress file** — Append-only log of what was done, what was learned
3. **Loop** — Each iteration: read PRD → pick next failing story → implement → test → commit if passing → update progress → repeat
4. **Stop condition** — All stories pass, or max iterations reached

## Core Pattern

```bash
while true; do cat PROMPT.md | claude -p; done
```

Or use the official `ralph-wiggum` plugin which implements this via a Stop hook with safety guards.

## PRD Format

```json
{
  "stories": [
    { "id": "1", "description": "Set up project structure", "passes": true },
    { "id": "2", "description": "Implement data model", "passes": false },
    { "id": "3", "description": "Add API endpoints", "passes": false }
  ]
}
```

Each iteration picks the first story where `passes: false`, implements it, runs tests, and flips to `true` if tests pass.

## Progress File

Append-only. Each entry records what happened in one iteration:

```
## Iteration 3 — Story 2: Implement data model
- Created src/models/user.ts with User and Profile entities
- Added Prisma schema migration
- Tests: 12 passed, 0 failed
- Committed: abc1234
- Learned: Prisma requires explicit relation fields on both sides
```

The "Learned" line is critical — it prevents the agent from repeating mistakes in future iterations.

## Safety Guards

- **Max iterations** — Always set a limit (default: 10). Prevents runaway loops.
- **Stuck detection** — If the same story fails 3 iterations in a row, stop and ask for help.
- **Commit gate** — Only commit when tests pass. Never commit broken code.
- **Progress check** — If progress file hasn't changed in 2 iterations, the agent is stuck.

## Hybrid Mode: Ralph Loop Inside Team Workflow

During Phase 2 (Build), the Team Lead can delegate a task to a sub-agent running in Ralph Loop mode. This works well for:

- Implementing a feature with incremental test-driven development
- Fixing a batch of related test failures
- Migrating code one module at a time

The Team Lead sets the PRD and iteration limit, the sub-agent loops until done or stuck, then returns results to the lead for integration.

## Model & Effort

| Mode | Model | Effort | Delegation |
|------|-------|--------|------------|
| Ralph Loop (standalone) | Fast (Sonnet) | Medium | None — single agent loops |
| Ralph Loop (inside Build) | Fast (Sonnet) | Medium | Sub-agent runs the loop |
