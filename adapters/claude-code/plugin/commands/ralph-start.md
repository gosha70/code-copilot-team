Start a Ralph Loop for autonomous task completion.

## Instructions

You are setting up a Ralph Loop — a single-agent autonomous loop that iterates until a task is complete.

### Step 1: Gather Requirements

Ask the user for:
1. **Task description** — what should be built or fixed?
2. **Completion criteria** — how do we know it's done? (test commands, expected outputs)
3. **Iteration limit** — how many iterations max? (suggest 10 for small tasks, 20 for medium)

If the user provides a PRD file path, read it instead of asking.

### Step 2: Generate the PRD

Create a `RALPH_PRD.json` file in the project root:

```json
{
  "task": "<task description>",
  "max_iterations": <limit>,
  "stories": [
    { "id": "1", "description": "<first incremental step>", "passes": false },
    { "id": "2", "description": "<second step>", "passes": false },
    { "id": "3", "description": "<third step>", "passes": false }
  ],
  "test_command": "<command to verify completion>",
  "stuck_threshold": 3
}
```

Rules for stories:
- Each story is a single, testable increment
- Stories are ordered — each builds on the previous
- 3-8 stories is ideal (too few = too coarse, too many = overhead)
- First story should be the simplest possible setup step

### Step 3: Create the Progress File

Create `RALPH_PROGRESS.md` in the project root:

```markdown
# Ralph Loop Progress

Task: <task description>
Started: <timestamp>

---
```

### Step 4: Create the Loop Prompt

Create `RALPH_PROMPT.md` in the project root:

```markdown
You are running in Ralph Loop mode. Read RALPH_PRD.json and RALPH_PROGRESS.md.

1. Find the first story where "passes" is false
2. If all stories pass → report completion and stop
3. Implement the story
4. Run the test command from the PRD
5. If tests pass → update the PRD (set passes: true), commit, append to RALPH_PROGRESS.md
6. If tests fail → append failure details and "Learned:" line to RALPH_PROGRESS.md
7. If the same story has failed <stuck_threshold> times in a row → stop and report

Always append to RALPH_PROGRESS.md with:
## Iteration N — Story X: <description>
- What was done
- Test result: pass/fail
- Committed: <hash> (if passing)
- Learned: <key insight for future iterations>
```

### Step 5: Explain Next Steps

Tell the user:

> Ralph Loop is set up. To run it:
>
> **Option A — Manual loop** (recommended for first time):
> ```bash
> while true; do cat RALPH_PROMPT.md | claude -p; done
> ```
>
> **Option B — With the ralph-wiggum plugin** (if installed):
> ```bash
> claude --plugin ralph-wiggum RALPH_PROMPT.md
> ```
>
> **To monitor progress:** check `RALPH_PROGRESS.md` in another terminal.
>
> **To stop:** Ctrl+C the loop, or the agent will stop when all stories pass or it gets stuck.

### Safety Reminders
- Always set `max_iterations` — never run unbounded
- Review `RALPH_PROGRESS.md` periodically for stuck patterns
- The loop creates one commit per passing story — easy to revert if needed
- If the agent gets stuck, start a new session with the problem description from the progress file
