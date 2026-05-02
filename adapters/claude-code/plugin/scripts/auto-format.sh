#!/usr/bin/env bash
set -euo pipefail

# auto-format.sh — PostToolUse hook (Edit|Write matcher)
#
# After a source file is edited, auto-detects and runs the project's formatter.
# Always exits 0 — formatting is fire-and-forget, never blocks Claude.

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

# --- Check if it's a formattable source file by extension ---
EXT="${FILE_PATH##*.}"
EXT_LOWER=$(echo "$EXT" | tr '[:upper:]' '[:lower:]')

# --- Resolve project directory ---
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
cd "$PROJECT_DIR" 2>/dev/null || exit 0

# --- Auto-detect formatter based on file extension ---
FORMAT_CMD=""

case "$EXT_LOWER" in
  ts|tsx|js|jsx|css|json)
    # Prettier: check for local install or package.json
    if [[ -x "node_modules/.bin/prettier" ]]; then
      FORMAT_CMD="npx prettier --write \"$FILE_PATH\""
    elif [[ -f "package.json" ]]; then
      FORMAT_CMD="npx prettier --write \"$FILE_PATH\""
    fi
    ;;

  py)
    # Python: prefer black, fallback to ruff format
    if [[ -f "poetry.lock" ]] && command -v poetry &>/dev/null; then
      if poetry run black --version &>/dev/null 2>&1; then
        FORMAT_CMD="poetry run black --quiet \"$FILE_PATH\""
      elif poetry run ruff --version &>/dev/null 2>&1; then
        FORMAT_CMD="poetry run ruff format \"$FILE_PATH\""
      fi
    elif [[ -f "uv.lock" ]] && command -v uv &>/dev/null; then
      if uv run black --version &>/dev/null 2>&1; then
        FORMAT_CMD="uv run black --quiet \"$FILE_PATH\""
      elif uv run ruff --version &>/dev/null 2>&1; then
        FORMAT_CMD="uv run ruff format \"$FILE_PATH\""
      fi
    elif [[ -x ".venv/bin/black" ]]; then
      FORMAT_CMD=".venv/bin/black --quiet \"$FILE_PATH\""
    elif [[ -x ".venv/bin/ruff" ]]; then
      FORMAT_CMD=".venv/bin/ruff format \"$FILE_PATH\""
    elif command -v black &>/dev/null; then
      FORMAT_CMD="black --quiet \"$FILE_PATH\""
    elif command -v ruff &>/dev/null; then
      FORMAT_CMD="ruff format \"$FILE_PATH\""
    fi
    ;;

  go)
    if command -v gofmt &>/dev/null; then
      FORMAT_CMD="gofmt -w \"$FILE_PATH\""
    fi
    ;;

  rs)
    if command -v rustfmt &>/dev/null; then
      FORMAT_CMD="rustfmt \"$FILE_PATH\""
    fi
    ;;

  java)
    if command -v google-java-format &>/dev/null; then
      FORMAT_CMD="google-java-format -i \"$FILE_PATH\""
    fi
    ;;
esac

# --- No formatter found: skip ---
if [[ -z "$FORMAT_CMD" ]]; then
  exit 0
fi

# --- Run formatter (always exit 0) ---
bash -c "$FORMAT_CMD" 2>&1 || {
  echo "auto-format: formatter failed for $FILE_PATH (non-blocking)" >&2
}

exit 0
