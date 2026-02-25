# Ralph Loop Guide

A comprehensive guide to using the Ralph Loop pattern for autonomous task completion.

## What Is Ralph Loop?

Ralph Loop (named after Ralph Wiggum) is a single-agent autonomous loop pattern. Instead of a human driving each step, the agent reads a plan, implements the next item, tests it, commits if passing, and repeats until done.

```
┌─────────────────────────────────────────┐
│  Read PRD → Pick next failing story     │
│       ↓                                 │
│  Implement the story                    │
│       ↓                                 │
│  Run tests                              │
│       ↓                                 │
│  Pass? → Commit + update PRD → Loop     │
│  Fail? → Log learnings → Loop           │
│  Stuck? → Stop and ask for help         │
└─────────────────────────────────────────┘
```

## When to Use

**Good fit:**
- Greenfield feature with a clear spec and test suite
- Fixing a batch of related test failures
- Migrating code one module at a time
- TDD-style development (write tests first, implement until green)
- Tasks expecting 3+ iterations

**Poor fit:**
- Tasks requiring design decisions mid-flight
- Multi-domain work that benefits from parallelism
- No automated tests to verify progress
- Exploratory work where requirements are unclear

## PRD Format

The PRD (Product Requirements Document) is a JSON file that tracks stories:

```json
{
  "task": "Add user authentication with magic links",
  "max_iterations": 15,
  "stories": [
    {
      "id": "1",
      "description": "Set up auth database tables (users, sessions, magic_links)",
      "passes": false
    },
    {
      "id": "2",
      "description": "Implement magic link generation and email sending",
      "passes": false
    },
    {
      "id": "3",
      "description": "Implement magic link verification and session creation",
      "passes": false
    },
    {
      "id": "4",
      "description": "Add protected route middleware",
      "passes": false
    },
    {
      "id": "5",
      "description": "Add login page UI and flow",
      "passes": false
    }
  ],
  "test_command": "npm test",
  "stuck_threshold": 3
}
```

### Story Writing Tips

- **One testable increment per story.** If you can't verify it with a test, it's too vague.
- **Order matters.** Each story should build on previous ones. Don't put "Add UI" before "Add API".
- **3-8 stories** is the sweet spot. Fewer = steps too large. More = overhead per iteration.
- **First story = simplest setup.** Get the foundation in place before building features.
- **Include the test in the description** if it's not obvious: "Add /health endpoint (GET returns 200)"

## Progress File

The progress file is append-only. Each iteration adds an entry:

```markdown
# Ralph Loop Progress

Task: Add user authentication with magic links
Started: 2026-02-22T10:30:00Z

---

## Iteration 1 — Story 1: Set up auth database tables
- Created migration 003_auth_tables.sql with users, sessions, magic_links tables
- Added indexes on email and token columns
- Tests: 8 passed, 0 failed
- Committed: a1b2c3d
- Learned: Prisma requires explicit @@index directives for composite indexes

## Iteration 2 — Story 2: Implement magic link generation
- Created src/auth/magic-link.ts with generate() and send() functions
- Added nodemailer dependency for email
- Tests: 12 passed, 0 failed
- Committed: e4f5g6h
- Learned: nodemailer needs SMTP config in .env; added to .env.example

## Iteration 3 — Story 3: Implement magic link verification
- Created src/auth/verify.ts with verify() function
- First attempt failed: token expiry check was using wrong timezone
- Tests: 14 passed, 1 failed → fixed timezone handling
- Tests: 15 passed, 0 failed
- Committed: i7j8k9l
- Learned: Always use UTC for token expiry comparisons, not local time
```

### Why "Learned" Matters

The "Learned" line is the most important part. It prevents the agent from repeating mistakes. In future iterations, the agent reads the full progress file and sees past failures and their solutions.

## Running the Loop

### Option 1: Manual Shell Loop

```bash
while true; do cat RALPH_PROMPT.md | claude -p; done
```

Press `Ctrl+C` to stop. The agent will also stop naturally when all stories pass.

### Option 2: Ralph Wiggum Plugin

If you have the official plugin installed:

```bash
claude --plugin ralph-wiggum RALPH_PROMPT.md
```

The plugin adds safety guards: max iteration enforcement, stuck detection, and graceful shutdown.

### Option 3: Slash Command

Use `/project:ralph-start` within a Claude Code session to set up the PRD, progress file, and prompt interactively.

## Safety Guards

| Guard | What It Does | Default |
|-------|-------------|---------|
| Max iterations | Stops after N iterations regardless of completion | 10 |
| Stuck threshold | Stops if the same story fails N times in a row | 3 |
| Commit gate | Only commits when tests pass | Always on |
| Progress check | Stops if progress file unchanged for 2 iterations | Always on |

### Setting Limits

Be conservative with `max_iterations`:
- Simple bug fix: 5
- Single feature: 10
- Multi-story feature: 15-20
- Large migration: 20-30

If you hit the limit, review progress and either increase it or restructure the remaining stories.

## Hybrid Mode: Ralph Loop + Team Workflow

During Phase 2 (Build), the Team Lead can delegate a bounded task to a sub-agent running in Ralph Loop:

1. Team Lead creates the PRD for one specific domain
2. Sub-agent runs the loop autonomously
3. Sub-agent returns results when done or stuck
4. Team Lead integrates with other agents' work

This works well when one part of the build is sequential (perfect for Ralph Loop) while other parts can be parallelized (team workflow).

## Troubleshooting

### Agent is stuck on the same story
- Check `RALPH_PROGRESS.md` for the "Learned" lines — is the agent learning from failures?
- The story may be too large. Split it into smaller steps.
- There may be an external dependency (missing env var, service not running). Fix it and restart.

### Agent commits broken code
- This shouldn't happen — the commit gate requires tests to pass.
- If it does, check that `test_command` in the PRD actually runs the relevant tests.
- Use `git revert` to undo the bad commit and restart.

### Agent finishes but the feature doesn't work
- The stories may not cover all requirements. Add more stories and restart.
- The test command may not be comprehensive enough. Improve tests first.

### Progress file is empty after several iterations
- The agent may not be reading `RALPH_PROMPT.md` correctly. Check the prompt format.
- The test command may be failing immediately (wrong command, missing deps).
