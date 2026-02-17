# Agent Interaction Traces

All agent transcripts are automatically saved to temporary files during execution.

## Location

Traces are stored at:

```
/private/tmp/claude-{session-id}/{project-path}/tasks/{agentId}.output
```

Each agent spawned by the Task tool gets its own output file named by agent ID (e.g., `a0b6bdb.output`).

## Accessing Traces

### List all agent sessions for a project

```bash
ls -lh /private/tmp/claude-{session-id}/{project-path}/tasks/
```

Example:
```bash
ls -lh /private/tmp/claude-501/-Users-gosha-dev-repo-bread-salt-bakery/tasks/
```

### View a specific agent's full transcript

```bash
cat /private/tmp/claude-{session-id}/{project-path}/tasks/{agentId}.output
```

Example:
```bash
cat /private/tmp/claude-501/-Users-gosha-dev-repo-bread-salt-bakery/tasks/a0b6bdb.output
```

### Search across all agents for a keyword

```bash
grep -r "keyword" /private/tmp/claude-{session-id}/{project-path}/tasks/
```

Example:
```bash
grep -r "Prisma" /private/tmp/claude-501/-Users-gosha-dev-repo-bread-salt-bakery/tasks/
```

### Tail a running agent's output in real-time

```bash
tail -f /private/tmp/claude-{session-id}/{project-path}/tasks/{agentId}.output
```

## Archiving Traces Permanently

**Important**: Traces in `/private/tmp/` are temporary and may be cleared on system restart.

To archive permanently:

```bash
# Create archive directory in your project
mkdir -p doc_internal/agent-traces

# Copy all traces
cp /private/tmp/claude-{session-id}/{project-path}/tasks/*.output doc_internal/agent-traces/

# Optionally rename with timestamps
for f in doc_internal/agent-traces/*.output; do
  mv "$f" "${f%.output}-$(date +%Y%m%d-%H%M%S).output"
done
```

Or archive with context:

```bash
# Create a session archive
mkdir -p doc_internal/agent-traces/session-$(date +%Y%m%d-%H%M%S)
cp /private/tmp/claude-{session-id}/{project-path}/tasks/*.output \
   doc_internal/agent-traces/session-$(date +%Y%m%d-%H%M%S)/
```

## What's in a Trace File

Each agent transcript includes:

- Full conversation history (all prompts and responses)
- Tool calls made (Read, Write, Edit, Bash, etc.)
- Tool results
- Errors and warnings
- Final summary returned to the parent agent
- Token usage and duration stats

## Use Cases

### Debugging agent behavior

When an agent produces unexpected output, review its trace to see:
- What files it read
- What assumptions it made
- Where it diverged from instructions

### Extracting generated code

If you want to review code an agent wrote without checking git diffs:
```bash
grep -A 20 "Write tool" /path/to/agent.output
```

### Understanding agent reasoning

Traces show the agent's internal thought process and decision-making.

### Documenting architectural decisions

Capture the rationale behind design choices made during agent execution.

### Training and retrospectives

Review traces after a session to understand what worked well and what didn't.

## Best Practices

1. **Archive after major phases** — don't rely on temporary files
2. **Include session metadata** — date, phase number, objective
3. **Add to .gitignore if sensitive** — traces may contain credentials or PII
4. **Review before sharing** — sanitize any secrets or sensitive data
