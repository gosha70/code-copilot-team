# Hooks — Manual Test Cases

## Commit Message

```
Add Phase 2 P0 hooks: verify-on-stop, verify-after-edit, notify

- verify-on-stop.sh: runs tests when Claude finishes (6 stacks)
- verify-after-edit.sh: runs type checker after edits (7 langs)
- notify.sh: desktop notifications (macOS/Linux)
- settings.json, docs/hooks-guide.md, setup automation
```

## Test Cases

### 1. claude-setup.sh installs hooks

```bash
cd claude_code && bash claude-setup.sh
ls ~/.claude/hooks/
jq '.hooks | keys' ~/.claude/settings.json
```

Expected: 3 `.sh` files; keys include Notification, PostToolUse, Stop

### 2. claude-setup.sh does not overwrite existing hooks config

```bash
# Run setup twice — second run should skip, not overwrite
bash claude-setup.sh
bash claude-setup.sh
```

Expected: second run prints `[skip] ... already has hooks configured`

### 3. claude-code init does NOT touch global settings

```bash
bash claude-code init web-static /tmp/test-project
rm -rf /tmp/test-project
```

Expected: no output about hooks or settings.json — init only creates project files

### 4. notify.sh shows desktop notification

```bash
echo '{"title":"Test","message":"Hook works"}' | ~/.claude/hooks/notify.sh
```

Expected: macOS notification banner appears

### 5. notify.sh skips empty message

```bash
echo '{"title":"Test","message":""}' | ~/.claude/hooks/notify.sh; echo $?
```

Expected: exit 0, no notification

### 6. verify-after-edit.sh skips non-source files

```bash
echo '{"tool_input":{"file_path":"README.md"}}' | ~/.claude/hooks/verify-after-edit.sh; echo $?
```

Expected: exit 0 (skipped, .md is not a source file)

### 7. verify-after-edit.sh runs tsc on TypeScript

```bash
# Run in a TypeScript project directory:
echo '{"tool_input":{"file_path":"src/index.ts"}}' \
  | CLAUDE_PROJECT_DIR="$(pwd)" ~/.claude/hooks/verify-after-edit.sh; echo $?
```

Expected: 0 if types pass, 2 with errors on stderr

### 8. verify-on-stop.sh infinite-loop guard

```bash
echo '{"stop_hook_active":true}' | ~/.claude/hooks/verify-on-stop.sh; echo $?
```

Expected: exit 0 immediately (no tests run)

### 9. verify-on-stop.sh skips when no test runner

```bash
echo '{"stop_hook_active":false}' \
  | CLAUDE_PROJECT_DIR=/tmp ~/.claude/hooks/verify-on-stop.sh; echo $?
```

Expected: exit 0 (no package.json/go.mod/etc found)

### 10. verify-on-stop.sh runs tests

```bash
# Run in a Node.js project with tests:
echo '{"stop_hook_active":false}' \
  | CLAUDE_PROJECT_DIR="$(pwd)" ~/.claude/hooks/verify-on-stop.sh; echo $?
```

Expected: 0 if tests pass, 2 with failure output on stderr
