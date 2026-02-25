# Post-Session Retrospective

Run a structured retrospective for the current session. Proposes rule and documentation changes but does not apply them.

## Steps

### 1. Session Summary

- Run `git log --oneline -20` and `git diff --stat` to see what changed
- Summarize: what was the goal? What was delivered?
- Note any gap between intent and outcome

### 2. Struggle Identification

Build a table of struggles encountered during this session:

| Struggle | Time Lost | Root Cause | Category |
|----------|-----------|------------|----------|
| {description} | {estimate} | {what was missing or wrong} | {underspec / tooling / convention / context loss} |

Categories:
- **underspec** — requirement was ambiguous or incomplete
- **tooling** — tool limitation or misconfiguration
- **convention** — rule missing or unclear
- **context loss** — agent forgot or lost track of earlier decisions

### 3. Rule/Doc Gap Analysis

For each struggle, propose a specific fix:

| Struggle | Proposed Fix | Target File |
|----------|-------------|-------------|
| {from table above} | {concrete change} | {path in shared/rules/, shared/templates/, or adapters/} |

Be specific: "Add rule X to file Y" not "improve documentation."

### 4. What Worked Well

- List patterns, rules, or workflows that prevented problems
- Identify agent configurations that were effective
- Note any conventions that saved time

### 5. Output

Write the retrospective to `doc_internal/retro-{YYYY-MM-DD}.md` (ask the user before writing).

Include all 4 sections above plus a summary of proposed changes.

**Important:** This command *proposes* rule changes but does not apply them. The user decides which proposals to implement.
