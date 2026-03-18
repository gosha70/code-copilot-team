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

  # Python — check for poetry/uv/pipenv/venv before bare pytest
  if [[ -f "$dir/pyproject.toml" || -f "$dir/setup.py" || -f "$dir/requirements.txt" ]]; then
    if [[ -f "$dir/poetry.lock" ]] && command -v poetry &>/dev/null; then
      TEST_CMD="poetry run pytest --tb=short -q"
      return
    elif [[ -f "$dir/uv.lock" ]] && command -v uv &>/dev/null; then
      TEST_CMD="uv run pytest --tb=short -q"
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

# --- Track overall failures ---
OVERALL_FAIL=0

# --- Guard against nonexistent project dir ---
if [[ ! -d "$PROJECT_DIR" ]]; then
  exit 0
fi
cd "$PROJECT_DIR"

# --- Run tests if runner detected ---
if [[ -n "$TEST_CMD" ]]; then
  if [[ -n "$TIMEOUT_CMD" ]]; then
    TEST_OUTPUT=$($TIMEOUT_CMD "$TIMEOUT" bash -c "$TEST_CMD" 2>&1) && TEST_EXIT=0 || TEST_EXIT=$?
  else
    TEST_OUTPUT=$(bash -c "$TEST_CMD" 2>&1) && TEST_EXIT=0 || TEST_EXIT=$?
  fi

  # --- Timeout (exit 124 from GNU timeout, 143 on some systems) ---
  if [[ $TEST_EXIT -eq 124 || $TEST_EXIT -eq 143 ]]; then
    echo "Test suite timed out after ${TIMEOUT}s. Skipping test verification." >&2
  elif [[ $TEST_EXIT -ne 0 ]]; then
    OVERALL_FAIL=$(( OVERALL_FAIL + 1 ))
    SUMMARY=$(echo "$TEST_OUTPUT" | tail -n 50)
    if [[ "$BLOCK" == "true" ]]; then
      echo "Tests failed. Fix the failures and try again." >&2
    else
      echo "Tests failed (report only — set HOOK_STOP_BLOCK=true to auto-fix)." >&2
    fi
    echo "" >&2
    echo "$SUMMARY" >&2
  fi
fi

# --- Infrastructure verification ---
# Combine tracked changes (staged+unstaged vs HEAD) with untracked new files
INFRA_FILES=$({ git diff --name-only HEAD 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null; } | grep -E '(Dockerfile|docker-compose\.yml|compose\.yml|\.github/workflows/.*\.yml)' | sort -u || true)

if [[ -n "$INFRA_FILES" ]]; then
  INFRA_TIMEOUT="${HOOK_INFRA_TIMEOUT:-120}"
  PROJECT_NAME="$(basename "$PROJECT_DIR")"

  DOCKER_FILES=$(echo "$INFRA_FILES" | grep -E '(Dockerfile|docker-compose\.yml|compose\.yml)' || true)
  if [[ -n "$DOCKER_FILES" ]] && ! command -v docker &>/dev/null; then
    OVERALL_FAIL=$(( OVERALL_FAIL + 1 ))
    echo "[infra] Docker not found — install Docker to verify infrastructure files." >&2
  elif command -v docker &>/dev/null; then
    # Docker build check — one pass per changed Dockerfile
    # Always use repo root as build context (COPY paths are relative to root, not Dockerfile dir)
    while IFS= read -r df; do
      [[ -z "$df" || ! -f "$df" ]] && continue
      if [[ -n "$TIMEOUT_CMD" ]]; then
        DBUILD_OUT=$($TIMEOUT_CMD "$INFRA_TIMEOUT" docker build -f "$df" -t "${PROJECT_NAME}-verify" "$PROJECT_DIR" 2>&1) && DBUILD_EXIT=0 || DBUILD_EXIT=$?
      else
        DBUILD_OUT=$(docker build -f "$df" -t "${PROJECT_NAME}-verify" "$PROJECT_DIR" 2>&1) && DBUILD_EXIT=0 || DBUILD_EXIT=$?
      fi
      if [[ $DBUILD_EXIT -ne 0 ]]; then
        OVERALL_FAIL=$(( OVERALL_FAIL + 1 ))
        echo "[infra] docker build FAILED: $df" >&2
        echo "$DBUILD_OUT" | tail -n 20 >&2
      else
        echo "[infra] docker build OK: $df" >&2
      fi
    done < <(echo "$INFRA_FILES" | grep -E 'Dockerfile' || true)

    # Docker Compose check — one pass per changed compose file
    while IFS= read -r cf; do
      [[ -z "$cf" || ! -f "$cf" ]] && continue
      cf_dir="$(dirname "$cf")"
      _compose_down() { (cd "$cf_dir" && docker compose down -v 2>/dev/null) || true; }
      trap _compose_down EXIT
      if [[ -n "$TIMEOUT_CMD" ]]; then
        (cd "$cf_dir" && $TIMEOUT_CMD "$INFRA_TIMEOUT" docker compose up --build -d 2>&1) && CUP_EXIT=0 || CUP_EXIT=$?
      else
        (cd "$cf_dir" && docker compose up --build -d 2>&1) && CUP_EXIT=0 || CUP_EXIT=$?
      fi
      if [[ $CUP_EXIT -eq 0 ]]; then
        sleep 15
        (cd "$cf_dir" && docker compose ps 2>&1)
        _compose_down
        trap - EXIT
        echo "[infra] docker compose OK: $cf" >&2
      else
        OVERALL_FAIL=$(( OVERALL_FAIL + 1 ))
        echo "[infra] docker compose up FAILED: $cf" >&2
        _compose_down
        trap - EXIT
      fi
    done < <(echo "$INFRA_FILES" | grep -E 'docker-compose\.yml|compose\.yml' || true)
  fi

  # CI workflow validation
  if echo "$INFRA_FILES" | grep -q '\.github/workflows/'; then
    while IFS= read -r wf; do
      [[ -z "$wf" || ! -f "$wf" ]] && continue
      if command -v actionlint &>/dev/null; then
        if actionlint "$wf" 2>&1; then
          echo "[infra] actionlint OK: $wf" >&2
        else
          OVERALL_FAIL=$(( OVERALL_FAIL + 1 ))
          echo "[infra] actionlint FAILED: $wf" >&2
        fi
      elif command -v python3 &>/dev/null && python3 -c "import yaml" 2>/dev/null; then
        if python3 -c "import yaml; yaml.safe_load(open('$wf'))" 2>&1; then
          echo "[infra] YAML OK: $wf" >&2
        else
          OVERALL_FAIL=$(( OVERALL_FAIL + 1 ))
          echo "[infra] YAML validation FAILED: $wf" >&2
        fi
      fi
    done < <(echo "$INFRA_FILES" | grep '\.github/workflows/' || true)
  fi
fi

# --- Shell script verification ---
SCRIPT_FILES=$({ git diff --name-only HEAD 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null; } | grep -E '\.sh$' | sort -u || true)

if [[ -n "$SCRIPT_FILES" ]]; then
  while IFS= read -r script; do
    [[ -z "$script" || ! -f "$script" ]] && continue
    if bash -n "$script" 2>&1; then
      echo "[scripts] bash -n OK: $script" >&2
      if [[ -x "$script" ]] && head -5 "$script" 2>/dev/null | grep -qi 'usage\|--help'; then
        bash "$script" --help 2>&1 || true
      fi
    else
      OVERALL_FAIL=$(( OVERALL_FAIL + 1 ))
      echo "[scripts] bash -n FAILED: $script" >&2
    fi
  done < <(echo "$SCRIPT_FILES")
fi

# --- Final result ---
if [[ $OVERALL_FAIL -gt 0 && "$BLOCK" == "true" ]]; then
  exit 2
fi
exit 0
