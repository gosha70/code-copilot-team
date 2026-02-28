---
applyTo: "**"
---

# Agent Team Protocol

Rules governing multi-agent delegation, phased workflows, and model selection.

## Three-Phase Workflow

Every non-trivial task follows three phases with distinct behaviors:

### Phase 1 — PLAN (Single Agent)
- **Model:** Highest-capability (e.g., Opus) · **Effort:** High
- Work alone. Do NOT delegate to sub-agents.
- Read the full codebase context, understand architecture, identify risks.
- **Ask clarifying questions** about data model shape, auth strategy, UI layout, and output formats BEFORE producing the plan. (See `clarification-protocol.md` for the full protocol and data model review gate.)
- Produce a concrete plan: files to touch, interfaces to change, test strategy.
- Get user approval before moving to Phase 2.

### Plan Approval Gate

Between Phase 1 (Plan) and Phase 2 (Build), a spec gate applies:

- Plan always emits `specs/<feature-id>/plan.md` with `spec_mode` frontmatter.
- For `full` or `lightweight`: Plan also emits `spec.md`. User approves both before Build.
- For `none`: User approves `plan.md` only. Build proceeds without a spec gate.
- All `[NEEDS CLARIFICATION]` markers in `spec.md` must be resolved before Build starts.

See `spec-workflow.md` for risk classification and required sections.

### Phase 2 — BUILD (Team Delegation)
- **Model:** Fast (e.g., Sonnet) · **Effort:** Medium
- Team Lead decomposes the approved plan into discrete tasks.
- Read `specs/<id>/plan.md` frontmatter to determine `spec_mode` gating behavior.
- Delegate each task to the appropriate specialist sub-agent via the Task tool.
- Each sub-agent works on ONE bounded task with explicit inputs/outputs.
- **Show the delegation plan to the user before executing.** List which agents, what tasks, in what order.
- Team Lead integrates results and resolves conflicts.
- **After each agent returns**: run type checker + dev server before delegating dependent work. (See `phase-workflow.md` § Pre-Build Verification.)

### Phase 3 — REVIEW (Single Agent)
- **Model:** Highest-capability (e.g., Opus) · **Effort:** High
- Work alone. Do NOT delegate.
- Review all changes holistically: correctness, consistency, style, test coverage.
- Run full test suite, verify no regressions.
- **Check browser console for runtime errors** — type checkers don't catch everything.
- Summarize what changed and any remaining concerns.

## Why Planning Must Not Delegate

Sub-agents only see fragments (one file, one module). Planning requires a holistic view of the entire system: how modules interact, where the boundaries are, what the risk surface looks like. Delegating planning produces fragmented, conflicting plans. Keep planning in one mind.

## Delegation Rules (Build Phase Only)

1. **One task per sub-agent.** Never ask a sub-agent to "implement the feature." Break it down: "Create the order repository interface" or "Add validation to the checkout form."
2. **Explicit context.** Tell each sub-agent which files to read, what interfaces to implement, and what constraints to respect.
3. **No chain delegation.** Sub-agents do not spawn their own sub-agents.
4. **Integrate immediately.** After each sub-agent returns, review its output and verify the build before delegating the next dependent task.
5. **Non-overlapping file ownership.** Every file has exactly one owner per phase. The lead handles shared/cross-cutting code after teammates return. (See `team-lead-efficiency.md`.)
6. **Right-size the team.** 2-3 teammates is the sweet spot. More increases coordination overhead without proportional speedup.

## Session Boundaries

### When to Start a New Session

Start a fresh session (`/clear` or new terminal) at these natural boundaries:

1. **After each completed phase.** Phase 1 → commit → new session → Phase 2. Never run Phases 1 through 4 in one session.
2. **After a commit.** If you've committed and the next task is unrelated, start fresh.
3. **When switching from planning to building.** The plan is captured in a file — the planning conversation is no longer needed.
4. **When debugging exceeds 10 exchanges.** If a bug takes more than 10 back-and-forth messages, the context is polluted with failed attempts. Start a new session with a clean description of the problem.
5. **When `/context` shows high usage.** If the visual grid is mostly full, compress with `/compact` or start fresh.

### Session Size Limits (Guidelines)

| Metric | Target | Maximum |
|---|---|---|
| User messages | 15-20 | 30 |
| Tool calls | 50-100 | 200 |
| Files changed | 10-20 | 40 |
| Duration | 1-2 hours | 4 hours |

These are guidelines, not hard rules. The point is: if you're approaching these limits, you should be asking "is it time for a fresh session?"

### Before Ending a Session

1. **Name the session**: `/rename "phase-2-auth-and-services"` — makes it easy to find later.
2. **Commit if ready**: Don't leave uncommitted work across session boundaries.
3. **Document what's pending**: If work remains, add it to a project-level tracking file (e.g., `doc_internal/TODO.md` or an MVP gap document).
4. **Save key decisions to memory**: `"remember that we chose magic link auth over password-based"`.

### Before Starting a New Session

1. **Read the project CLAUDE.md** — it reloads automatically, but verify it's up to date.
2. **Read any pending TODO / gap documents** — start with awareness of what's left.
3. **Reference the last commit** — `git log -1 --oneline` to orient yourself.
4. **State the objective clearly** — "Implement Phase 3 per the plan in doc_internal/PLAN.md" is better than "continue where we left off."

### Context Window Exhaustion Patterns

From real projects, these are the most common causes of context exhaustion:

| Cause | Sessions Affected | Prevention |
|---|---|---|
| Running 4 phases in one session | Mega-sessions (4+ hours) | One phase per session |
| Extended debugging cycles | Auth failures, config issues | Cap at 10 exchanges; fresh session with clean problem description |
| Pasting large error outputs | Console dumps, stack traces | Paste only the relevant error line, not the full output |
| Repeatedly reading the same files | Agent re-reading files after each message | Use `/compact` to summarize; reference by path |
| Large file rewrites | Agent regenerating entire files | Use targeted edits (diff-over-rewrite) |

### The Ideal Session Arc

```
1. Orient (2 min)    — read CLAUDE.md, check git status, state objective
2. Plan (5-10 min)   — review or create plan for this phase
3. Build (30-90 min) — execute the plan, delegate if needed
4. Verify (5-10 min) — type check, lint, build, smoke test
5. Commit (2 min)    — commit with descriptive message
6. Close (1 min)     — rename session, document pending work
```

Total: 45 minutes to 2 hours. If it's taking longer, consider splitting.

## Context Efficiency

- **One task per session.** Start a new session for unrelated work.
- **Use `/compact` at task boundaries** to reclaim context space.
- **Use `/clear` between task switches** when changing focus entirely.
- **Point to files by path** rather than pasting large blocks into the prompt.
- **Diff over rewrite.** Prefer targeted edits over regenerating entire files.

## Single-Agent Loop Mode (Ralph Loop)

An alternative to team delegation during Build. A single agent runs in a loop: read plan → implement next item → test → commit if passing → repeat.

**When to use instead of team delegation:**
- Task is sequential (each step depends on the previous)
- Clear, testable completion criteria exist
- No human design decisions needed mid-flight
- Parallelism wouldn't help (single-domain work)

**When to use team delegation instead:**
- Multiple independent domains can be parallelized
- Human judgment needed during implementation
- No test suite to verify progress automatically

The Team Lead can also use hybrid mode: delegate a Ralph Loop sub-agent for one bounded task during Build while handling other tasks directly.

See `ralph-loop.md` for the full pattern, PRD format, and safety guards.

## Model & Effort Quick Reference

| Phase    | Model Tier       | Effort | Delegation |
|----------|------------------|--------|------------|
| Plan     | Highest (Opus)   | High   | None       |
| Build    | Fast (Sonnet)    | Medium | Yes        |
| Build (loop) | Fast (Sonnet) | Medium | None — single agent loops |
| Review   | Highest (Opus)   | High   | None       |
| Quick fix| Fastest (Haiku)  | Low    | None       |
