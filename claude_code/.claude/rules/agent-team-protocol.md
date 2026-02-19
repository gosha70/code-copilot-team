# Agent Team Protocol

Rules governing multi-agent delegation, phased workflows, and model selection.

## Three-Phase Workflow

Every non-trivial task follows three phases with distinct behaviors:

### Phase 1 — PLAN (Single Agent)
- **Model:** Highest-capability (e.g., Opus) · **Effort:** High
- Work alone. Do NOT delegate to sub-agents.
- Read the full codebase context, understand architecture, identify risks.
- **Ask clarifying questions** about data model shape, auth strategy, UI layout, and output formats BEFORE producing the plan. (See `clarification-protocol.md`.)
- Produce a concrete plan: files to touch, interfaces to change, test strategy.
- Get user approval before moving to Phase 2.

### Phase 2 — BUILD (Team Delegation)
- **Model:** Fast (e.g., Sonnet) · **Effort:** Medium
- Team Lead decomposes the approved plan into discrete tasks.
- Delegate each task to the appropriate specialist sub-agent via the Task tool.
- Each sub-agent works on ONE bounded task with explicit inputs/outputs.
- **Show the delegation plan to the user before executing.** List which agents, what tasks, in what order.
- Team Lead integrates results and resolves conflicts.
- **After each agent returns**: run type checker + dev server before delegating dependent work. (See `pre-build-verification.md`.)

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

- **One phase per session.** Do not run Phases 1 through 4 in a single session — context exhaustion degrades quality in later phases.
- **Commit at phase boundaries.** Commit, rename the session, start fresh for the next phase.
- **If debugging exceeds 10 exchanges**, start a new session with a clean problem description.
- See `session-splitting.md` for full session management rules.

## Context Efficiency

- **One task per session.** Start a new session for unrelated work.
- **Use `/compact` at task boundaries** to reclaim context space.
- **Use `/clear` between task switches** when changing focus entirely.
- **Point to files by path** rather than pasting large blocks into the prompt.
- **Diff over rewrite.** Prefer targeted edits over regenerating entire files.

## Model & Effort Quick Reference

| Phase    | Model Tier       | Effort | Delegation |
|----------|------------------|--------|------------|
| Plan     | Highest (Opus)   | High   | None       |
| Build    | Fast (Sonnet)    | Medium | Yes        |
| Review   | Highest (Opus)   | High   | None       |
| Quick fix| Fastest (Haiku)  | Low    | None       |
