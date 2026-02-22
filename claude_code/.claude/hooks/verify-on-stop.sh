#!/usr/bin/env bash
set -euo pipefail

# verify-on-stop.sh — Stop hook
#
# When Claude finishes responding, auto-detects and runs the project's test
# suite. By default, reports results without blocking (exit 0). Set
# HOOK_STOP_BLOCK=true to make Claude continue fixing on failure (exit 2).
#
# Checks stop_hook_active to prevent infinite loops: if this hook already
# triggered once in the current stop cycle, it exits immediately.

# --- jq guard ---
if ! command -v jq &>/dev/null; then
  echo "jq not found; hook skipped. Install jq for hook support." >&2
  exit 0
fi

# --- Read event JSON from stdin ---
INPUT=$(cat)

# --- Infinite-loop guard ---
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null) || exit 0
if [[ "$STOP_HOOK_ACTIVE" == "true" ]]; then
  exit 0
fi

# --- Resolve project directory ---
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

# --- Configuration ---
# HOOK_TEST_TIMEOUT: max seconds for test runner (default 120)
# HOOK_STOP_BLOCK:   set to "true" to block Claude on failure (default: report only)
TIMEOUT="${HOOK_TEST_TIMEOUT:-120}"
BLOCK="${HOOK_STOP_BLOCK:-false}"

# --- Detect timeout command (GNU coreutils vs macOS Homebrew) ---
TIMEOUT_CMD=""
if command -v timeout &>/dev/null; then
  TIMEOUT_CMD="timeout"
elif command -v gtimeout &>/dev/null; then
  TIMEOUT_CMD="gtimeout"
fi

# --- Auto-detect test runner ---
TEST_CMD=""

detect_test_runner() {
  local dir="$1"

  # Node.js / TypeScript
  if [[ -f "$dir/package.json" ]]; then
    local has_test
    has_test=$(jq -r '.scripts.test // empty' "$dir/package.json" 2>/dev/null) || true
    if [[ -n "$has_test" ]]; then
      if [[ -f "$dir/pnpm-lock.yaml" ]]; then
        TEST_CMD="pnpm test"
      elif [[ -f "$dir/yarn.lock" ]]; then
        TEST_CMD="yarn test"
      elif [[ -f "$dir/bun.lockb" || -f "$dir/bun.lock" ]]; then
        TEST_CMD="bun test"
      else
        TEST_CMD="npm test"
      fi
      return
    fi
  fi

  # Python — check for poetry/pipenv/venv before bare pytest
  if [[ -f "$dir/pyproject.toml" || -f "$dir/setup.py" || -f "$dir/requirements.txt" ]]; then
    if [[ -f "$dir/poetry.lock" ]] && command -v poetry &>/dev/null; then
      TEST_CMD="poetry run pytest --tb=short -q"
      return
    elif [[ -f "$dir/Pipfile.lock" ]] && command -v pipenv &>/dev/null; then
      TEST_CMD="pipenv run pytest --tb=short -q"
      return
    elif [[ -x "$dir/.venv/bin/pytest" ]]; then
      TEST_CMD="$dir/.venv/bin/pytest --tb=short -q"
      return
    elif command -v pytest &>/dev/null; then
      TEST_CMD="pytest --tb=short -q"
      return
    elif command -v python3 &>/dev/null; then
      TEST_CMD="python3 -m pytest --tb=short -q 2>/dev/null || python3 -m unittest discover -s tests -q"
      return
    fi
  fi

  # Go
  if [[ -f "$dir/go.mod" ]]; then
    TEST_CMD="go test ./..."
    return
  fi

  # Java — Maven
  if [[ -f "$dir/pom.xml" ]]; then
    TEST_CMD="mvn test -q"
    return
  fi

  # Java — Gradle
  if [[ -f "$dir/build.gradle" || -f "$dir/build.gradle.kts" ]]; then
    TEST_CMD="./gradlew test"
    return
  fi

  # Rust
  if [[ -f "$dir/Cargo.toml" ]]; then
    TEST_CMD="cargo test"
    return
  fi
}

detect_test_runner "$PROJECT_DIR"

# --- No test runner found: skip gracefully ---
if [[ -z "$TEST_CMD" ]]; then
  exit 0
fi

# --- Run tests (with timeout if available) ---
cd "$PROJECT_DIR"

if [[ -n "$TIMEOUT_CMD" ]]; then
  TEST_OUTPUT=$($TIMEOUT_CMD "$TIMEOUT" bash -c "$TEST_CMD" 2>&1) && TEST_EXIT=0 || TEST_EXIT=$?
else
  TEST_OUTPUT=$(bash -c "$TEST_CMD" 2>&1) && TEST_EXIT=0 || TEST_EXIT=$?
fi

# --- Timeout (exit 124 from GNU timeout, 143 on some systems) ---
if [[ $TEST_EXIT -eq 124 || $TEST_EXIT -eq 143 ]]; then
  echo "Test suite timed out after ${TIMEOUT}s. Skipping verification." >&2
  exit 0
fi

# --- Tests passed ---
if [[ $TEST_EXIT -eq 0 ]]; then
  exit 0
fi

# --- Tests failed ---
SUMMARY=$(echo "$TEST_OUTPUT" | tail -n 50)

if [[ "$BLOCK" == "true" ]]; then
  # Blocking mode: Claude continues fixing
  echo "Tests failed. Fix the failures and try again." >&2
  echo "" >&2
  echo "$SUMMARY" >&2
  exit 2
else
  # Report-only mode (default): show results, let Claude stop
  echo "Tests failed (report only — set HOOK_STOP_BLOCK=true to auto-fix)." >&2
  echo "" >&2
  echo "$SUMMARY" >&2
  exit 0
fi
