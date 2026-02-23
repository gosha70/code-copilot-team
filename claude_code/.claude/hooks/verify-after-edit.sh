#!/usr/bin/env bash
set -euo pipefail

# verify-after-edit.sh — PostToolUse hook (Edit|Write matcher)
#
# After a source file is edited, auto-detects and runs the project's type
# checker. By default, reports errors without blocking (exit 0). Set
# HOOK_EDIT_BLOCK=true to feed errors back to Claude for auto-fix (exit 2).
#
# Non-source files (.md, .json, .yaml, .env, etc.) are silently skipped.

# --- jq guard ---
if ! command -v jq &>/dev/null; then
  echo "jq not found; hook skipped. Install jq for hook support." >&2
  exit 0
fi

# --- Read event JSON from stdin ---
INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0
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

# --- Configuration ---
# HOOK_EDIT_BLOCK: set to "true" to block Claude on failure (default: report only)
BLOCK="${HOOK_EDIT_BLOCK:-false}"

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
  if [[ -f "poetry.lock" ]] && command -v poetry &>/dev/null; then
    CHECK_CMD="poetry run mypy --no-error-summary \"$FILE_PATH\" 2>/dev/null || poetry run pyright \"$FILE_PATH\" 2>/dev/null"
  elif [[ -f "uv.lock" ]] && command -v uv &>/dev/null; then
    # uv-managed project: try mypy via uv run, fall back to ruff check
    if uv run mypy --version &>/dev/null 2>&1; then
      CHECK_CMD="uv run mypy --no-error-summary \"$FILE_PATH\""
    elif uv run ruff --version &>/dev/null 2>&1; then
      CHECK_CMD="uv run ruff check \"$FILE_PATH\""
    fi
  elif [[ -x ".venv/bin/mypy" ]]; then
    CHECK_CMD=".venv/bin/mypy --no-error-summary \"$FILE_PATH\""
  elif [[ -x ".venv/bin/ruff" ]]; then
    CHECK_CMD=".venv/bin/ruff check \"$FILE_PATH\""
  elif command -v mypy &>/dev/null; then
    CHECK_CMD="mypy --no-error-summary \"$FILE_PATH\""
  elif command -v pyright &>/dev/null; then
    CHECK_CMD="pyright \"$FILE_PATH\""
  elif command -v ruff &>/dev/null; then
    CHECK_CMD="ruff check \"$FILE_PATH\""
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

# --- Failed ---
SUMMARY=$(echo "$CHECK_OUTPUT" | tail -n 30)

if [[ "$BLOCK" == "true" ]]; then
  # Blocking mode: Claude auto-fixes
  echo "Type check failed after editing ${FILE_PATH}. Fix the errors:" >&2
  echo "" >&2
  echo "$SUMMARY" >&2
  exit 2
else
  # Report-only mode (default): show errors, let Claude proceed
  echo "Type check failed after editing ${FILE_PATH} (report only — set HOOK_EDIT_BLOCK=true to auto-fix)." >&2
  echo "" >&2
  echo "$SUMMARY" >&2
  exit 0
fi
