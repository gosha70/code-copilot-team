# Team Lead Efficiency

Rules for the lead agent when coordinating sub-agents to minimize waste and maximize throughput.

## Task Scoping

### Right-Size the Work

- **2-3 teammates** is the sweet spot for most features. More than 3 increases coordination overhead without proportional speedup.
- Each teammate task should take **5-30 minutes**. If a task takes over an hour, it's too large — break it up.
- If a task would touch fewer than 3 files, the lead should do it directly instead of delegating.

### Non-Overlapping Ownership

Every file must have exactly ONE owner for a given phase:

**Bad**:
```
Agent A: Implement product service (touches product model, router, UI)
Agent B: Implement order service (also touches product model for inventory)
```

**Good**:
```
Agent A: Implement product service (owns product.service, product.router)
Agent B: Implement order service (owns order.service, order.router)
Lead: Handles shared code (product model changes for inventory) after both complete
```

The lead handles **shared/cross-cutting code** after teammates return — not in parallel.

### Clear Boundaries in the Delegation Prompt

Every delegation must include:

1. **Exact files to create or modify** (not "implement the feature").
2. **Read-only context files** — schema, types, design docs the agent should reference but NOT modify.
3. **Interface contracts** — what inputs/outputs must match.
4. **What NOT to do** — explicit exclusions prevent scope creep.

## Polling Discipline

### Do Not Busy-Wait on Teammates

After launching sub-agents, the lead should:

1. **Launch all independent agents at once** (parallel, not sequential).
2. **Work on non-overlapping tasks** while waiting (documentation, tests, review plans).
3. **Check status periodically** — not continuously. Polling once per minute is sufficient.
4. **Never re-do teammate work.** If a teammate is slow, wait or stop them — don't duplicate their output.

### When to Stop a Teammate

Stop a running teammate if:

- Its task is no longer needed (requirements changed).
- The lead has already completed the work (this means the task was mis-delegated).
- The agent has been running over 2x the expected duration with no progress.

Don't stop a teammate just because it's slower than expected — context switching is expensive.

## Integration Sequence

After all teammates return:

1. **Read each teammate's output** before making changes.
2. **Run type checker** across the full codebase (catches cross-agent incompatibilities).
3. **Run the dev server** (catches runtime issues).
4. **Fix integration issues** — the lead resolves conflicts, not another sub-agent.
5. **Report results to user** — summarize what each agent delivered, any issues found, and what was fixed.

## Anti-Patterns From Real Projects

| Anti-Pattern | What Happened | Prevention |
|---|---|---|
| **434 TaskList polls** | Lead busy-waited on 3 teammates, wasting tokens | Poll once per minute; work on other tasks while waiting |
| **Lead duplicated teammate work** | Lead started implementing what a teammate was assigned | Never overlap — if you assigned it, wait for it |
| **Teammate stopped early** | Lead stopped a slow teammate and redid the work | Only stop if the work is no longer needed |
| **Too many teammates** | 3 teammates for a task where 2 would suffice | Start with 2; add a 3rd only if there's a genuinely independent third domain |
| **Vague delegation** | "Implement the frontend pages" with no file list | Always specify exact files and acceptance criteria |
