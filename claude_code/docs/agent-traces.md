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

Example (replace placeholders with your values):
```bash
ls -lh /private/tmp/claude-{uid}/-Users-yourname-dev-my-project/tasks/
```

### View a specific agent's full transcript

```bash
cat /private/tmp/claude-{session-id}/{project-path}/tasks/{agentId}.output
```

### Search across all agents for a keyword

```bash
grep -r "keyword" /private/tmp/claude-{session-id}/{project-path}/tasks/
```

### Tail a running agent's output in real-time

```bash
tail -f /private/tmp/claude-{session-id}/{project-path}/tasks/{agentId}.output
```

## Finding Your Session ID

The session ID is typically your Unix UID. Find it with:
```bash
ls /private/tmp/ | grep claude-
```

The project path is your working directory with `/` replaced by `-` and a leading `-`.

## Archiving Traces Permanently

**Important**: Traces in `/private/tmp/` are temporary and may be cleared on system restart.

To archive permanently:

```bash
# Create archive directory in your project
mkdir -p doc_internal/agent-traces

# Copy all traces
cp /private/tmp/claude-{session-id}/{project-path}/tasks/*.output \
   doc_internal/agent-traces/

# Optionally rename with timestamps
for f in doc_internal/agent-traces/*.output; do
    mv "$f" "${f%.output}-$(date +%Y%m%d-%H%M%S).output"
done
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

- **Debugging agent behavior** — see what files it read, what assumptions it made, where it diverged from instructions.
- **Extracting generated code** — review code an agent wrote without checking git diffs.
- **Understanding agent reasoning** — traces show the agent's thought process and decision-making.
- **Documenting architectural decisions** — capture the rationale behind design choices.
- **Training and retrospectives** — review traces to understand what worked well and what didn't.

## Best Practices

1. **Archive after major phases** — don't rely on temporary files.
2. **Include session metadata** — date, phase number, objective.
3. **Add to .gitignore if sensitive** — traces may contain credentials or PII.
4. **Review before sharing** — sanitize any secrets or sensitive data.
