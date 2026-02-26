# Debugging Strategies for Claude Code

Techniques for diagnosing and resolving issues during Claude Code sessions.

---

## 1. `/doctor` — Health Check

Run `/doctor` to verify your Claude Code environment is working correctly.

**What it checks:**
- CLI version and available updates
- Authentication status (API key / OAuth)
- MCP server connectivity
- Hook script syntax and permissions
- Settings file validity (`settings.json`, `CLAUDE.md`)
- Model access and quota

**When to use:**
- Session won't start or crashes immediately
- MCP tools suddenly unavailable
- Hooks not firing after a config change
- After upgrading Claude Code

**Interpreting results:**
- Green checks = healthy; no action needed
- Yellow warnings = degraded; the listed component may cause issues
- Red failures = broken; fix before continuing (error message includes remediation steps)

---

## 2. Background Tasks

Use background shell tasks to monitor long-running processes without blocking your session.

### Tail logs in background

```bash
# Start a background log tail
tail -f /tmp/my-app.log &

# Monitor test output
npm run test:watch > /tmp/test-output.log 2>&1 &
```

### Error monitoring pattern

```bash
# Watch for errors in a running service
tail -f logs/app.log | grep -i "error\|exception\|fatal" &
```

### Health check loop

```bash
# Poll a service endpoint every 10 seconds
while true; do
  curl -sf http://localhost:3000/health || echo "$(date): health check failed"
  sleep 10
done &
```

### Tips
- Use `jobs` to list background tasks, `kill %N` to stop one
- Redirect output to a file so Claude can read results later
- Background tasks persist within the current shell session only

---

## 3. MCP-Based Console Inspection

Use the [Playwright MCP server](https://github.com/anthropics/mcp-playwright) for browser-level debugging.

### Setup

Add to your `.claude/settings.json`:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@anthropic-ai/mcp-playwright"]
    }
  }
}
```

### Debugging patterns

| Pattern | MCP Tool | What it reveals |
|---|---|---|
| Console errors | `browser_console` | Runtime JS errors, failed assertions, React warnings |
| DOM state | `browser_snapshot` | Current page structure, visibility, accessibility tree |
| Network failures | `browser_network` | Failed API calls, CORS errors, 4xx/5xx responses |
| Screenshots | `browser_screenshot` | Visual rendering issues, layout bugs, responsive breakpoints |

### Workflow

1. Start the dev server (`npm run dev` or equivalent)
2. Use `browser_navigate` to open the page
3. Use `browser_console` to check for errors
4. Use `browser_snapshot` to inspect DOM state
5. Fix issues and repeat

This is especially useful for debugging UI issues that don't surface in test output.

---

## 4. Agent Trace Debugging

Claude Code saves full transcripts for every session. See [agent-traces.md](agent-traces.md) for storage locations and archival.

### Quick reference

```bash
# Find recent traces (macOS)
ls -lt ~/.claude/projects/*/traces/*.jsonl | head -5

# Search for errors across traces
grep -l "error\|Error\|ERROR" ~/.claude/projects/*/traces/*.jsonl

# Read a specific trace
cat ~/.claude/projects/<project>/traces/<session-id>.jsonl | jq '.'
```

### Common patterns

| Symptom | What to look for in trace | Likely cause |
|---|---|---|
| Wrong file edited | Tool calls targeting unexpected paths | Ambiguous instructions or stale context |
| Loop / repeated attempts | Same tool call appearing 3+ times | Missing dependency or incorrect assumption |
| Sub-agent wrong output | Delegated task prompt in trace | Insufficient context passed to sub-agent |
| Silent failure | Tool call with empty or error result | Permission denied or missing tool |
| Context lost mid-session | Compression event in trace | Context window filled; use `/compact` earlier |

---

## 5. Common Debugging Workflows

### Build fails after edit

1. Read the error output from `verify-after-edit` hook
2. Check if `remediation.json` has a matching hint
3. If type error: fix the type, don't suppress it
4. If missing import: check if a dependency was removed or renamed
5. Run the build command manually to see full output

### Tests pass locally, fail in hook

1. Check if the hook runs in a different working directory
2. Verify environment variables are available in hook context
3. Check hook timeout — `verify-on-stop.sh` has 180s, large suites may need more
4. Run the exact hook command manually: `bash .claude/hooks/verify-on-stop.sh`

### Session context lost

1. Check if auto-compression happened (trace will show a compression event)
2. Use `/compact` proactively with a focus hint before context fills
3. Put critical context in `CLAUDE.md` or project files rather than relying on chat history
4. For cross-session context, use GCC memory (see `gcc-protocol.md`)

### Sub-agent produces wrong output

1. Read the trace to find the delegated task prompt
2. Check if sufficient context was passed (file paths, constraints, expected output)
3. Verify the sub-agent has the right tools available
4. Consider whether the task should be handled directly instead of delegated
