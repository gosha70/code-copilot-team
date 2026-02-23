# Team Delegation

Rules for the Build phase when coordinating sub-agents.

## Delegation Rules

1. **One task per sub-agent.** Break work into bounded pieces: "Create the order repository" not "implement the feature."
2. **Explicit context.** Tell each sub-agent which files to read, what interfaces to implement, what constraints to respect.
3. **No chain delegation.** Sub-agents do not spawn their own sub-agents.
4. **Integrate immediately.** Review output and verify the build after each sub-agent returns.
5. **Non-overlapping file ownership.** Every file has exactly one owner per phase. The lead handles shared/cross-cutting code after teammates return.
6. **Right-size the team.** 2-3 teammates is the sweet spot. More increases coordination overhead.

## Task Scoping

- Each teammate task should take **5-30 minutes**. Larger → break it up.
- If a task touches fewer than **3 files**, the lead should do it directly.
- Every delegation prompt must include:
  - **Exact files** to create or modify
  - **Read-only context files** (schema, types, design docs)
  - **Interface contracts** (inputs/outputs that must match)
  - **Exclusions** (what NOT to do)

## Polling Discipline

- Launch all independent agents at once (parallel).
- Work on non-overlapping tasks while waiting (docs, tests, review plans).
- Check status periodically, not continuously.
- Never re-do teammate work. If a teammate is slow, wait — don't duplicate.

## Post-Agent Verification

After each sub-agent returns:

1. Run the type checker across the **entire** codebase (not just the agent's files)
2. Run the linter
3. Start the dev server — verify no runtime errors in the console
4. If the agent touched API routes or services, make a test request

After parallel agents complete, also check:
- Do frontend calls match backend API signatures?
- Are shared types consistent across modules?
- Are imports resolving correctly?

## Anti-Patterns

- **Busy-waiting:** Lead polled TaskList 434 times instead of doing other work. Poll once per minute.
- **Duplicate work:** Lead started implementing what a teammate was assigned. Never overlap.
- **Vague delegation:** "Implement the frontend" with no file list. Always specify exact files and acceptance criteria.

## Ralph Loop (Single-Agent Autonomous Loop)

Use Ralph Loop instead of team delegation when:
- The task has clear, testable completion criteria
- A plan is approved and doesn't need human decisions mid-flight
- Work is sequential (each step depends on the previous)
- You expect 3+ iterations to reach completion

**How it works:** A single agent loops: read PRD → pick next failing story → implement → test → commit if passing → update progress → repeat. Each iteration appends to a progress file including a "Learned" line to prevent repeating mistakes.

**Safety guards:**
- Max iterations limit (default: 10)
- Stuck detection: same story fails 3 iterations → stop and ask for help
- Commit gate: only commit when tests pass
- Progress check: no progress in 2 iterations → agent is stuck
