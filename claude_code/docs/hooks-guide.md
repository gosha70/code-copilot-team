# Hooks Guide

## What Ships With This Configuration

Three hook scripts that enforce rules deterministically instead of relying on the LLM to remember them.

| Hook | Event | What It Does |
|------|-------|-------------|
| `verify-on-stop.sh` | Stop | Runs the project test suite when Claude finishes. If tests fail, feeds errors back so Claude continues fixing. |
| `verify-after-edit.sh` | PostToolUse (Edit\|Write) | Runs the project type checker after source file edits. Feeds type errors back immediately. |
| `notify.sh` | Notification | Sends desktop notifications (macOS/Linux) when Claude needs input. |

All hooks auto-detect your project's stack — no configuration per language needed.

## Installation

All three hooks are installed automatically by `claude-setup.sh`:

```bash
./claude-setup.sh
```

This installs:
- Hook scripts to `~/.claude/hooks/`
- Hook wiring to `~/.claude/settings.json`

The hooks are **globally active** in all Claude Code sessions immediately after setup. No per-project configuration needed.

Source scripts are also available in `.claude/hooks/` within this repository for reference.

---

## How Hooks Work

Hooks are shell scripts that Claude Code runs at specific lifecycle events.

**Input:** JSON on stdin containing session info and event-specific fields.

**Exit codes:**
- `0` — success; Claude proceeds normally
- `2` — block/feedback; effect depends on event type:
  - **Stop hooks:** Claude continues working (doesn't stop)
  - **PostToolUse hooks:** stderr content is fed back to Claude as context
- Any other code — hook failure (logged, Claude proceeds)

**Output:**
- stdout — data passed back to Claude Code (JSON or plain text)
- stderr — error messages fed to Claude (on exit code 2) or logged

---

## Verifying the Hooks Are Active

After running `claude-setup.sh`, confirm the hooks are installed:

```bash
ls -la ~/.claude/hooks/
cat ~/.claude/settings.json
```

You should see all three scripts in `~/.claude/hooks/` and the hooks wiring in `~/.claude/settings.json`.

---

## Disabling Individual Hooks

Remove the hook entry from `.claude/settings.json` (project) or `~/.claude/settings.json` (global).

The hook scripts can remain on disk — they only run when wired in settings.json. To temporarily disable without editing JSON, rename the script:

```bash
mv .claude/hooks/verify-on-stop.sh .claude/hooks/verify-on-stop.sh.disabled
```

To disable all hooks at once, add to settings.json:

```json
{
  "disableAllHooks": true
}
```

---

## Customizing

### Timeouts

Each hook has a `timeout` field in settings.json (milliseconds):

| Hook | Default | When to increase |
|------|---------|-----------------|
| `verify-on-stop.sh` | 180000 (3 min) | Slow test suites |
| `verify-after-edit.sh` | 30000 (30 sec) | Large TypeScript projects |
| `notify.sh` | 10000 (10 sec) | Rarely needed |

### Internal test timeout

`verify-on-stop.sh` has its own internal timeout (default 120 seconds) that kills the test runner if it hangs. This is separate from the settings.json timeout. Override via environment variable:

```bash
export HOOK_TEST_TIMEOUT=300
```

### Matchers

The `matcher` field in settings.json is a regex that filters when the hook fires:

| Matcher | Meaning |
|---------|---------|
| `""` (empty) | Fire on all events of that type |
| `"Edit\|Write"` | Fire on Edit or Write tools |
| `"Edit"` | Fire on Edit tool only |
| `"Bash"` | Fire on Bash tool only |

---

## Supported Stacks

### verify-on-stop.sh — Test runners

| Stack | Detected By | Command |
|-------|-------------|---------|
| Node.js | `package.json` with `scripts.test` | npm/yarn/pnpm/bun test |
| Python | `pyproject.toml` / `setup.py` / `requirements.txt` | `pytest --tb=short -q` |
| Go | `go.mod` | `go test ./...` |
| Java (Maven) | `pom.xml` | `mvn test -q` |
| Java (Gradle) | `build.gradle` / `build.gradle.kts` | `./gradlew test` |
| Rust | `Cargo.toml` | `cargo test` |

Package manager detection for Node.js: `pnpm-lock.yaml` → pnpm, `yarn.lock` → yarn, `bun.lockb` / `bun.lock` → bun, otherwise npm.

### verify-after-edit.sh — Type checkers

| Extensions | Detected By | Command |
|-----------|-------------|---------|
| `.ts`, `.tsx`, `.js`, `.jsx` | `tsconfig.json` | `npx tsc --noEmit` |
| `.py` | `mypy` or `pyright` on PATH | `mypy <file>` or `pyright <file>` |
| `.go` | `go.mod` | `go vet ./...` |
| `.java` | `pom.xml` or `build.gradle` | `mvn compile -q` or `./gradlew compileJava -q` |
| `.rs` | `Cargo.toml` | `cargo check` |
| `.kt` | `build.gradle` / `build.gradle.kts` | `./gradlew compileKotlin -q` |
| `.cs` | `dotnet` on PATH | `dotnet build --no-restore -q` |

Non-source files (`.md`, `.json`, `.yaml`, `.env`, etc.) are silently skipped.

---

## Writing Custom Hooks

### Input JSON by event type

**Stop hook:**

```json
{
  "session_id": "...",
  "cwd": "/project/path",
  "hook_event_name": "Stop",
  "stop_hook_active": false,
  "last_assistant_message": "..."
}
```

`stop_hook_active` is `true` when Claude is already continuing due to a previous Stop hook invocation. Always check this to prevent infinite loops.

**PostToolUse hook:**

```json
{
  "session_id": "...",
  "cwd": "/project/path",
  "hook_event_name": "PostToolUse",
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "/project/src/index.ts",
    "old_string": "...",
    "new_string": "..."
  },
  "tool_response": { "success": true }
}
```

**Notification hook:**

```json
{
  "session_id": "...",
  "cwd": "/project/path",
  "hook_event_name": "Notification",
  "title": "Claude Code",
  "message": "Waiting for permission...",
  "notification_type": "permission_prompt"
}
```

Notification types: `permission_prompt`, `idle_prompt`, `auth_success`, `elicitation_dialog`.

### Template for a custom hook

```bash
#!/usr/bin/env bash
set -euo pipefail

# Guard: skip if jq is not installed
if ! command -v jq &>/dev/null; then
  exit 0
fi

# Read event JSON from stdin
INPUT=$(cat)

# Parse fields
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Your logic here...

# Exit 0 to pass, exit 2 to block/feed back errors via stderr
exit 0
```

### Environment variables

| Variable | Description |
|----------|-------------|
| `CLAUDE_PROJECT_DIR` | Absolute path to the project root |

### Hook precedence

Both project (`.claude/settings.json`) and global (`~/.claude/settings.json`) hooks run. Project hooks do not override global hooks — both execute. Global hooks run first, then project hooks.

---

## Dependencies

All hooks require:

- **bash** — any modern version (4.0+)
- **jq** — JSON parser

Install jq:

```bash
# macOS
brew install jq

# Ubuntu/Debian
sudo apt install jq

# Fedora/RHEL
sudo dnf install jq
```

The hooks gracefully skip if jq is not available (exit 0 with no action).

`verify-on-stop.sh` optionally uses `timeout` (GNU coreutils) for test runner timeouts. On macOS, install via `brew install coreutils` (provides `gtimeout`). Without it, the test runner runs without an internal timeout (the settings.json timeout still applies as a hard ceiling).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Hook doesn't fire | Not wired in settings.json | Check `.claude/settings.json` has the hook entry |
| "jq not found" in verbose output | jq not installed | Install jq (see Dependencies) |
| Type check runs on .md files | Shouldn't happen (extension filter) | Check hook version; `.md` is not in the source extensions list |
| Tests hang forever | No internal timeout + slow suite | Set `HOOK_TEST_TIMEOUT=60` or install GNU coreutils for `timeout` |
| Claude keeps looping on test failures | Tests are genuinely broken | The `stop_hook_active` guard limits to one retry. If tests still fail, Claude stops. |
| No desktop notification on Linux | `notify-send` not installed | Install `libnotify-bin` (Ubuntu) or `libnotify` (Fedora) |
