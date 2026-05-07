---
applyTo: "**"
---


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

## Opus 4.7 Behavioral Changes

When the Team Lead is running on Opus 4.7, the defaults shift in ways that affect delegation:

- **Spawns fewer subagents by default.** Opus 4.7 prefers to do work inline rather than fan out — it will often handle tasks directly that Opus 4.6 would have delegated.
- **Calls tools less often.** More reasoning per turn, fewer redundant reads or repeated greps.
- **Calibrates response length to task complexity.** Won't over-explain a simple fix, and won't pad short answers.

These defaults are usually what you want. When they aren't, **be explicit in the prompt:**

| If you need…              | Say so explicitly                                                                  |
|---------------------------|------------------------------------------------------------------------------------|
| More subagents            | "Use subagents to investigate X and Y in parallel."                                |
| More tool use             | "Read files A, B, C and compare their interfaces before proposing the change."     |
| Verbose output            | "Provide a detailed analysis with code examples and line-number citations."        |
| A specific decomposition  | "Split this into three tasks: schema, API, UI. Delegate each to its own subagent." |

Do not assume Opus 4.7 will infer the same delegation defaults Opus 4.6 used. If you've been running with `xhigh` effort and noticing thinner output than you expected, the cause is usually the model right-sizing — not the effort level.

## Cycle-Transition Handoff (Recommend, Don't Ask)

When a session starts after a cycle has shipped — or when `/cooldown` has just finished writing its report — the Team Lead's first message must lead with a **concrete recommendation**, not an open-ended `"What's next?"`.

### The rule

If the answer to a candidate question is already in the project's documentation — `CLAUDE.md`, `AGENTS.md`, `ROADMAP.md` (when the consuming project ships one), or `specs/pitches/*/pitch.md` frontmatter — **recommend, don't ask**. Authorizing the next bet stays explicit (the user still runs `/bet` and `/cycle-start`); the change is *how* you ask, not *whether* you ask.

### Procedure at session start after a shipped cycle

1. **Read the cooldown report.** Look for `specs/retros/cooldown-after-<NN>.md` matching the most recent `cycle-<NN>.md`. If present, the `cooldown-report` agent has already named the recommended next bet — surface its `Next-bet recommendation` line verbatim.
2. **Otherwise, derive it.** Read `ROADMAP.md` if present at the consuming project's repo root (`code-copilot-team` itself does not ship one — this is for downstream projects). If absent, scan `specs/pitches/*/pitch.md` for `bet_status: shaped` and rank by appetite-fit + scope clarity + circuit-breaker concreteness.
3. **Lead with the recommendation, not a question:**

   **Bad** — open-ended deferral when the roadmap already has the answer:

   ```
   Cycle 0 shipped. PR merged. Cycle 1 (foundation) is shaped.
   What's next?
   ```

   **Good** — concrete recommendation with the exact commands:

   ```
   Cycle 0 shipped. PR merged. Cycle 1 (foundation) is shaped and is the
   next bet per ROADMAP. Recommend `/bet 0001-foundation` followed by
   `/cycle-start 0001-foundation`. Confirm?
   ```

4. **Fall back to listing candidates only when genuinely ambiguous.** If multiple shaped pitches tie with no clear ordering, OR if no shaped pitches exist, then a list-and-ask prompt is appropriate. Default to recommendation; ask only when you must.

### Why this matters

The agent labelling cycle 1 as "the natural next bet" in its own state table and then asking the user `"What's next?"` anyway is the failure mode issue #25 documents. The answer is in the question. It forces a round-trip the user shouldn't have to make, trains the user to ignore the agent's own reasoning, and slows momentum at exactly the moment Shape-Up wants the next bet locked.

See also: `claude_code/.claude/agents/cooldown-report.md` (the agent that emits the recommendation), `claude_code/.claude/commands/cooldown.md` (the command that surfaces it), and `docs/shape-up-workflow.md` § "Cycle-transition handoff".

## Anti-Patterns From Real Projects

| Anti-Pattern | What Happened | Prevention |
|---|---|---|
| **434 TaskList polls** | Lead busy-waited on 3 teammates, wasting tokens | Poll once per minute; work on other tasks while waiting |
| **Lead duplicated teammate work** | Lead started implementing what a teammate was assigned | Never overlap — if you assigned it, wait for it |
| **Teammate stopped early** | Lead stopped a slow teammate and redid the work | Only stop if the work is no longer needed |
| **Too many teammates** | 3 teammates for a task where 2 would suffice | Start with 2; add a 3rd only if there's a genuinely independent third domain |
| **Vague delegation** | "Implement the frontend pages" with no file list | Always specify exact files and acceptance criteria |
| **"What's next?" after a shipped cycle** | Lead asked open-endedly when the roadmap had already named the next bet | Surface the cooldown-report's `Next-bet recommendation` verbatim; ask only on genuine ambiguity (issue #25) |
