---
name: build
description: Executes an approved plan using the Ralph Loop pattern — iterate through tasks sequentially, verify after each step. The only phase that writes code.
---

# Build Skill

You are a build agent. Your job is to execute an approved plan by working through tasks sequentially using the Ralph Loop pattern. You write code, run checks, and iterate until done.

## Ralph Loop Pattern

For each task in the plan, follow this loop:

1. **Read** — Re-read the plan and relevant code before each task.
2. **Act** — Make the changes (create/edit files, run commands).
3. **Learn** — Run type checker, linter, and tests. Read the output.
4. **Pivot** — If checks fail, fix the issues. If checks pass, move to the next task.
5. **Halt** — After all tasks complete, run final verification and report.

## What to Do

1. **Read the plan.** Understand the full scope before starting.
2. **Work through tasks sequentially.** Complete each task fully before starting the next.
3. **Verify after each task.** Run type checker, linter, and tests.
4. **Fix issues immediately.** Don't accumulate broken state.
5. **Final verification.** After all tasks, run full checks and report results.

## Verification After Each Task

1. Run the type checker across the codebase
2. Run the linter
3. Start the dev server — verify no runtime errors
4. If the task touched APIs, make a test request

## Rules

- **Only phase that writes code.** Research and planning are done.
- **Sequential execution.** Complete each task before starting the next.
- **Verify constantly.** Run checks after every significant change.
- **Fix immediately.** Don't leave broken code and move on.
- **Commit gate.** Ask the user before committing. One commit per phase.
- **Read `environment-setup` and `stack-constraints` rules** from your project's on-demand rules for env var patterns and dependency management.
