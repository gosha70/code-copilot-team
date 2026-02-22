#!/usr/bin/env bash
set -euo pipefail

# verify-after-edit.sh — PostToolUse hook (Edit|Write matcher)
#
# After a source file is edited, auto-detects and runs the project's type
# checker. If the check fails, exits 2 with error output on stderr so Claude
# receives feedback and can fix the issue.
#
# Non-source files (.md, .json, .yaml, .env, etc.) are silently skipped.

# --- jq guard ---
if ! command -v jq &>/dev/null; then
  echo "jq not found; hook skipped. Install jq for hook support." >&2
  exit 0
fi

# --- Read event JSON from stdin ---
INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# --- Check if it's a source file by extension ---
SOURCE_EXTENSIONS="ts tsx js jsx py go java rs kt scala cs cpp c h hpp"

EXT="${FILE_PATH##*.}"
EXT_LOWER=$(echo "$EXT" | tr '[:upper:]' '[:lower:]')

IS_SOURCE=false
for src_ext in $SOURCE_EXTENSIONS; do
  if [[ "$EXT_LOWER" == "$src_ext" ]]; then
    IS_SOURCE=true
    break
  fi
done

if [[ "$IS_SOURCE" != "true" ]]; then
  exit 0
fi

# --- Resolve project directory ---
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
cd "$PROJECT_DIR"

# --- Auto-detect type checker based on file extension ---
CHECK_CMD=""

if [[ "$EXT_LOWER" =~ ^(ts|tsx|js|jsx)$ ]]; then
  if [[ -f "tsconfig.json" ]]; then
    CHECK_CMD="npx tsc --noEmit"
  fi

elif [[ "$EXT_LOWER" == "py" ]]; then
  if command -v mypy &>/dev/null; then
    CHECK_CMD="mypy --no-error-summary \"$FILE_PATH\""
  elif command -v pyright &>/dev/null; then
    CHECK_CMD="pyright \"$FILE_PATH\""
  fi

elif [[ "$EXT_LOWER" == "go" ]]; then
  if [[ -f "go.mod" ]]; then
    CHECK_CMD="go vet ./..."
  fi

elif [[ "$EXT_LOWER" == "java" ]]; then
  if [[ -f "pom.xml" ]]; then
    CHECK_CMD="mvn compile -q"
  elif [[ -f "build.gradle" || -f "build.gradle.kts" ]]; then
    CHECK_CMD="./gradlew compileJava -q"
  fi

elif [[ "$EXT_LOWER" == "rs" ]]; then
  if [[ -f "Cargo.toml" ]]; then
    CHECK_CMD="cargo check 2>&1"
  fi

elif [[ "$EXT_LOWER" == "kt" ]]; then
  if [[ -f "build.gradle" || -f "build.gradle.kts" ]]; then
    CHECK_CMD="./gradlew compileKotlin -q"
  fi

elif [[ "$EXT_LOWER" == "cs" ]]; then
  if command -v dotnet &>/dev/null; then
    CHECK_CMD="dotnet build --no-restore -q"
  fi
fi

# --- No type checker found: skip ---
if [[ -z "$CHECK_CMD" ]]; then
  exit 0
fi

# --- Run type checker ---
CHECK_OUTPUT=$(bash -c "$CHECK_CMD" 2>&1) && CHECK_EXIT=0 || CHECK_EXIT=$?

if [[ $CHECK_EXIT -eq 0 ]]; then
  exit 0
fi

# --- Failed: feed errors back to Claude (truncated to last 30 lines) ---
SUMMARY=$(echo "$CHECK_OUTPUT" | tail -n 30)
echo "Type check failed after editing ${FILE_PATH}. Fix the errors:" >&2
echo "" >&2
echo "$SUMMARY" >&2
exit 2
