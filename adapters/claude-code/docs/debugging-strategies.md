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

## 3. Browser Debugging with Playwright

Use [Playwright CLI](https://github.com/microsoft/playwright-cli) for browser-level debugging. It's token-efficient and works natively with Claude Code's shell access.

### Setup

```bash
# One-time install (or use setup.sh --playwright)
npm install -g @playwright/cli@latest
playwright-cli install --skills
```

### Debugging patterns

| Pattern | Command | What it reveals |
|---|---|---|
| Open page | `playwright-cli open <url>` | Navigate to the page, start a session |
| Console errors | `playwright-cli console` | Runtime JS errors, React warnings |
| DOM state | `playwright-cli snapshot` | Current page structure, accessibility tree |
| Screenshots | `playwright-cli screenshot` | Visual rendering issues, layout bugs |
| Click/interact | `playwright-cli click "Button text"` | Trigger UI actions, test flows |

### Workflow

1. Start the dev server (`npm run dev` or equivalent)
2. `playwright-cli open http://localhost:<port>`
3. `playwright-cli snapshot` to inspect DOM state
4. `playwright-cli screenshot` to capture visual state
5. Fix issues and repeat

### Alternative: Playwright MCP (Docker/CI)

For containerized environments without shell access, use [Playwright MCP](https://github.com/microsoft/playwright-mcp):

```bash
claude mcp add --scope project --transport stdio playwright -- \
  npx -y @playwright/mcp@latest --headless
```

See [recommended-mcp-servers.md](recommended-mcp-servers.md) for full setup options including Docker.

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
4. For cross-session continuity, keep critical context in `CLAUDE.md`, specs, and phase recaps

### Sub-agent produces wrong output

1. Read the trace to find the delegated task prompt
2. Check if sufficient context was passed (file paths, constraints, expected output)
3. Verify the sub-agent has the right tools available
4. Consider whether the task should be handled directly instead of delegated
