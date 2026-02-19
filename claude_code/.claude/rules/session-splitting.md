# Session Splitting Protocol

Rules for managing session boundaries to prevent context exhaustion and maintain quality.

## When to Start a New Session

Start a fresh session (`/clear` or new terminal) at these natural boundaries:

1. **After each completed phase.** Phase 1 → commit → new session → Phase 2. Never run Phases 1 through 4 in one session.
2. **After a commit.** If you've committed and the next task is unrelated, start fresh.
3. **When switching from planning to building.** The plan is captured in a file — the planning conversation is no longer needed.
4. **When debugging exceeds 10 exchanges.** If a bug takes more than 10 back-and-forth messages, the context is polluted with failed attempts. Start a new session with a clean description of the problem.
5. **When `/context` shows high usage.** If the visual grid is mostly full, compress with `/compact` or start fresh.

## Session Size Limits (Guidelines)

| Metric | Target | Maximum |
|---|---|---|
| User messages | 15-20 | 30 |
| Tool calls | 50-100 | 200 |
| Files changed | 10-20 | 40 |
| Duration | 1-2 hours | 4 hours |

These are guidelines, not hard rules. The point is: if you're approaching these limits, you should be asking "is it time for a fresh session?"

## Before Ending a Session

1. **Name the session**: `/rename "phase-2-auth-and-services"` — makes it easy to find later.
2. **Commit if ready**: Don't leave uncommitted work across session boundaries.
3. **Document what's pending**: If work remains, add it to a project-level tracking file (e.g., `doc_internal/TODO.md` or an MVP gap document).
4. **Save key decisions to memory**: `"remember that we chose magic link auth over password-based"`.

## Before Starting a New Session

1. **Read the project CLAUDE.md** — it reloads automatically, but verify it's up to date.
2. **Read any pending TODO / gap documents** — start with awareness of what's left.
3. **Reference the last commit** — `git log -1 --oneline` to orient yourself.
4. **State the objective clearly** — "Implement Phase 3 per the plan in doc_internal/PLAN.md" is better than "continue where we left off."

## Context Window Exhaustion Patterns

From real projects, these are the most common causes of context exhaustion:

| Cause | Sessions Affected | Prevention |
|---|---|---|
| Running 4 phases in one session | Mega-sessions (4+ hours) | One phase per session |
| Extended debugging cycles | Auth failures, config issues | Cap at 10 exchanges; fresh session with clean problem description |
| Pasting large error outputs | Console dumps, stack traces | Paste only the relevant error line, not the full output |
| Repeatedly reading the same files | Agent re-reading files after each message | Use `/compact` to summarize; reference by path |
| Large file rewrites | Agent regenerating entire files | Use targeted edits (diff-over-rewrite) |

## The Ideal Session Arc

```
1. Orient (2 min)    — read CLAUDE.md, check git status, state objective
2. Plan (5-10 min)   — review or create plan for this phase
3. Build (30-90 min) — execute the plan, delegate if needed
4. Verify (5-10 min) — type check, lint, build, smoke test
5. Commit (2 min)    — commit with descriptive message
6. Close (1 min)     — rename session, document pending work
```

Total: 45 minutes to 2 hours. If it's taking longer, consider splitting.
