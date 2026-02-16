# Agent Team Protocol

Rules governing multi-agent delegation, phased workflows, and model selection.

## Three-Phase Workflow

Every non-trivial task follows three phases with distinct behaviors:

### Phase 1 — PLAN (Single Agent)
- **Model:** Highest-capability (e.g., Opus) · **Effort:** High
- Work alone. Do NOT delegate to sub-agents.
- Read the full codebase context, understand architecture, identify risks.
- Produce a concrete plan: files to touch, interfaces to change, test strategy.
- Get user approval before moving to Phase 2.

### Phase 2 — BUILD (Team Delegation)
- **Model:** Fast (e.g., Sonnet) · **Effort:** Medium
- Team Lead decomposes the approved plan into discrete tasks.
- Delegate each task to the appropriate specialist sub-agent via the Task tool.
- Each sub-agent works on ONE bounded task with explicit inputs/outputs.
- Team Lead integrates results and resolves conflicts.

### Phase 3 — REVIEW (Single Agent)
- **Model:** Highest-capability (e.g., Opus) · **Effort:** High
- Work alone. Do NOT delegate.
- Review all changes holistically: correctness, consistency, style, test coverage.
- Run full test suite, verify no regressions.
- Summarize what changed and any remaining concerns.

## Why Planning Must Not Delegate

Sub-agents only see fragments (one file, one module). Planning requires a holistic
view of the entire system: how modules interact, where the boundaries are, what
the risk surface looks like. Delegating planning produces fragmented, conflicting
plans. Keep planning in one mind.

## Delegation Rules (Build Phase Only)

1. **One task per sub-agent.** Never ask a sub-agent to "implement the feature."
   Break it down: "Create the repository interface in src/repos/order.py."
2. **Explicit context.** Tell each sub-agent which files to read, what interfaces
   to implement, and what constraints to respect.
3. **No chain delegation.** Sub-agents do not spawn their own sub-agents.
4. **Integrate immediately.** After each sub-agent returns, review its output
   before delegating the next dependent task.

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
