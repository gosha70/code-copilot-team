# Workflow

## Three-Phase Workflow

| Phase | Model | Effort | Delegation |
|-------|-------|--------|------------|
| Plan | Highest (Opus) | High | None — work alone |
| Build | Fast (Sonnet) | Medium | Yes — delegate to specialists |
| Build (loop) | Fast (Sonnet) | Medium | None — single agent loops |
| Review | Highest (Opus) | High | None — work alone |
| Quick fix | Fastest (Haiku) | Low | None |

## Phase Rules

**Plan:** Work alone. Read full codebase context, understand architecture, identify risks. Ask clarifying questions about data model, auth, UI, output format before producing the plan. Get user approval before Build.

**Build:** Team Lead decomposes the approved plan into discrete tasks. Show the delegation plan to the user before executing. Delegate each task to the appropriate specialist. Each sub-agent works on ONE bounded task with explicit inputs/outputs. Integrate results and resolve conflicts. After each agent returns, run type checker + dev server before delegating dependent work.

**Review:** Work alone. Review all changes holistically: correctness, consistency, style, test coverage. Run full test suite. Check browser console for runtime errors. Summarize what changed and any remaining concerns.

## Session Boundaries

Start a fresh session at these boundaries:

1. After each completed phase — commit, rename session, start fresh
2. After a commit when the next task is unrelated
3. When switching from planning to building
4. When debugging exceeds 10 exchanges — start fresh with clean problem description
5. When context usage is high — use `/compact` or start fresh

## Post-Phase Checklist

Before declaring a phase complete:

- [ ] Type checker passes (`tsc --noEmit`, `mypy`, `go vet`, etc.)
- [ ] Linter passes with zero errors
- [ ] Dependencies installed and verified (install → build → run)
- [ ] Dev server builds and runs without crashes
- [ ] Browser console has no errors (missing modules, hydration mismatches)
- [ ] Manual smoke test completed (auth flows, API calls, UI interactions)
- [ ] If auth included: verified end-to-end (login, protected routes, logout)
- [ ] Commit is granular — one phase per commit
- [ ] User approves before starting next phase

## Context Efficiency

- One task per session. Start a new session for unrelated work.
- Point to files by path rather than pasting large blocks.
- Use `/compact` at task boundaries to reclaim context.
- Use `/clear` between task switches.
- Prefer targeted edits over regenerating entire files.
