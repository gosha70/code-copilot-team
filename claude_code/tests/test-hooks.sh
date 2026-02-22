#!/usr/bin/env bash

# test-hooks.sh — Automated tests for hook scripts
#
# Run from the repo root:
#   bash claude_code/tests/test-hooks.sh

HOOKS_DIR="$(cd "$(dirname "$0")/../.claude/hooks" && pwd)"
PASS=0
FAIL=0

assert_exit() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$actual" -eq "$expected" ]]; then
    echo "  PASS: $name (exit $actual)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (expected exit $expected, got $actual)"
    FAIL=$((FAIL + 1))
  fi
}

# Run a hook, return its exit code. Extra args are env vars (KEY=VAL).
run_hook() {
  local hook="$1"
  local input="$2"
  shift 2
  local rc=0
  printf '%s' "$input" | env "$@" bash "$HOOKS_DIR/$hook" >/dev/null 2>/dev/null || rc=$?
  echo "$rc"
}

echo "=== notify.sh ==="

RC=$(run_hook notify.sh '{"title":"Test","message":"hello"}')
assert_exit "valid notification" 0 "$RC"

RC=$(run_hook notify.sh '{"title":"Test","message":""}')
assert_exit "empty message skips" 0 "$RC"

RC=$(run_hook notify.sh '{}')
assert_exit "missing fields" 0 "$RC"

RC=$(run_hook notify.sh '')
assert_exit "empty input" 0 "$RC"

RC=$(run_hook notify.sh 'not json')
assert_exit "invalid JSON" 0 "$RC"

echo ""
echo "=== verify-on-stop.sh ==="

RC=$(run_hook verify-on-stop.sh '{"stop_hook_active":true}')
assert_exit "loop guard exits immediately" 0 "$RC"

RC=$(run_hook verify-on-stop.sh '{"stop_hook_active":false}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "no test runner in /tmp" 0 "$RC"

RC=$(run_hook verify-on-stop.sh '{}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "missing stop_hook_active" 0 "$RC"

RC=$(run_hook verify-on-stop.sh '' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "empty input" 0 "$RC"

RC=$(run_hook verify-on-stop.sh 'not json' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "invalid JSON" 0 "$RC"

RC=$(run_hook verify-on-stop.sh '{"stop_hook_active":false}' CLAUDE_PROJECT_DIR=/nonexistent)
assert_exit "nonexistent project dir" 0 "$RC"

RC=$(run_hook verify-on-stop.sh '{"stop_hook_active":true}' HOOK_STOP_BLOCK=true)
assert_exit "loop guard in block mode" 0 "$RC"

RC=$(run_hook verify-on-stop.sh '{"stop_hook_active":false}' CLAUDE_PROJECT_DIR=/tmp HOOK_STOP_BLOCK=true)
assert_exit "block mode no test runner" 0 "$RC"

echo ""
echo "=== verify-after-edit.sh ==="

RC=$(run_hook verify-after-edit.sh '{"tool_input":{"file_path":"README.md"}}')
assert_exit "markdown skips" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '{"tool_input":{"file_path":"config.json"}}')
assert_exit "json skips" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '{"tool_input":{"file_path":".env"}}')
assert_exit "env skips" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '{"tool_input":{"file_path":"style.css"}}')
assert_exit "css skips" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '{"tool_input":{"file_path":"data.yaml"}}')
assert_exit "yaml skips" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '{"tool_input":{"file_path":"Makefile"}}')
assert_exit "no-extension skips" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '{}')
assert_exit "missing file_path" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '')
assert_exit "empty input" 0 "$RC"

RC=$(run_hook verify-after-edit.sh 'not json')
assert_exit "invalid JSON" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '{"tool_input":{"file_path":"test.ts"}}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "ts no tsconfig" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '{"tool_input":{"file_path":"test.go"}}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "go no go.mod" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '{"tool_input":{"file_path":"test.rs"}}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "rust no Cargo.toml" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '{"tool_input":{"file_path":"test.java"}}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "java no pom/gradle" 0 "$RC"

RC=$(run_hook verify-after-edit.sh '{"tool_input":{"file_path":"test.py"}}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "python no type checker" 0 "$RC"

echo ""
echo "=== auto-format.sh ==="

RC=$(run_hook auto-format.sh '{"tool_input":{"file_path":"app.ts"}}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "ts source file (no formatter)" 0 "$RC"

RC=$(run_hook auto-format.sh '{"tool_input":{"file_path":"main.py"}}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "py source file (no formatter)" 0 "$RC"

RC=$(run_hook auto-format.sh '{"tool_input":{"file_path":"main.go"}}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "go source file" 0 "$RC"

RC=$(run_hook auto-format.sh '{"tool_input":{"file_path":"README.md"}}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "markdown skips" 0 "$RC"

RC=$(run_hook auto-format.sh '{"tool_input":{"file_path":"data.yaml"}}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "yaml skips" 0 "$RC"

RC=$(run_hook auto-format.sh '{}')
assert_exit "missing file_path" 0 "$RC"

RC=$(run_hook auto-format.sh '')
assert_exit "empty input" 0 "$RC"

RC=$(run_hook auto-format.sh 'not json')
assert_exit "invalid JSON" 0 "$RC"

echo ""
echo "=== protect-files.sh ==="

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":".env"}}')
assert_exit ".env blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":".env.local"}}')
assert_exit ".env.local blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":".env.production"}}')
assert_exit ".env.production blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":"package-lock.json"}}')
assert_exit "package-lock.json blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":"yarn.lock"}}')
assert_exit "yarn.lock blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":"poetry.lock"}}')
assert_exit "poetry.lock blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":"Cargo.lock"}}')
assert_exit "Cargo.lock blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":".git/config"}}')
assert_exit ".git/ path blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":"credentials.json"}}')
assert_exit "credentials.json blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":"server.pem"}}')
assert_exit ".pem file blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":"private.key"}}')
assert_exit ".key file blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":"config/secrets.yaml"}}')
assert_exit "path with secret blocked" 2 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":"src/app.ts"}}')
assert_exit "normal source allowed" 0 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":"README.md"}}')
assert_exit "README allowed" 0 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":"src/main.py"}}')
assert_exit "python source allowed" 0 "$RC"

RC=$(run_hook protect-files.sh '{"tool_input":{"file_path":".env"}}' HOOK_PROTECT_ALLOW=true)
assert_exit "override allows .env" 0 "$RC"

RC=$(run_hook protect-files.sh '{}')
assert_exit "missing file_path" 0 "$RC"

RC=$(run_hook protect-files.sh '')
assert_exit "empty input" 0 "$RC"

RC=$(run_hook protect-files.sh 'not json')
assert_exit "invalid JSON" 0 "$RC"

echo ""
echo "=== reinject-context.sh ==="

RC=$(run_hook reinject-context.sh '{}' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "empty project dir" 0 "$RC"

RC=$(run_hook reinject-context.sh '' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "empty input" 0 "$RC"

RC=$(run_hook reinject-context.sh 'not json' CLAUDE_PROJECT_DIR=/tmp)
assert_exit "invalid JSON" 0 "$RC"

RC=$(run_hook reinject-context.sh '{}' CLAUDE_PROJECT_DIR=/nonexistent)
assert_exit "nonexistent project dir" 0 "$RC"

# Test with a git repo (current repo)
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
RC=$(run_hook reinject-context.sh '{}' CLAUDE_PROJECT_DIR="$REPO_DIR")
assert_exit "valid git repo" 0 "$RC"

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
