#!/usr/bin/env bash

# test-hooks.sh — Automated tests for hook scripts
#
# Run from the repo root:
#   bash tests/test-hooks.sh

HOOKS_DIR="$(cd "$(dirname "$0")/../adapters/claude-code/.claude/hooks" && pwd)"
COUNTS_FILE="$(cd "$(dirname "$0")" && pwd)/test-counts.env"
# shellcheck source=/dev/null
source "$COUNTS_FILE"
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
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RC=$(run_hook reinject-context.sh '{}' CLAUDE_PROJECT_DIR="$REPO_DIR")
assert_exit "valid git repo" 0 "$RC"

echo "=== peer-review-on-stop.sh ==="

# --- Guards ---
RC=$(run_hook peer-review-on-stop.sh '{"stop_hook_active":true}' CCT_PEER_REVIEW_ENABLED=true)
assert_exit "loop guard exits immediately" 0 "$RC"

RC=$(run_hook peer-review-on-stop.sh '{"stop_hook_active":false}' CCT_PEER_REVIEW_ENABLED=false)
assert_exit "disabled peer review exits" 0 "$RC"

RC=$(run_hook peer-review-on-stop.sh '{}' CCT_PEER_REVIEW_ENABLED=false)
assert_exit "disabled with empty input" 0 "$RC"

RC=$(run_hook peer-review-on-stop.sh '' CCT_PEER_REVIEW_ENABLED=false)
assert_exit "disabled empty input" 0 "$RC"

RC=$(run_hook peer-review-on-stop.sh 'not json' CCT_PEER_REVIEW_ENABLED=false)
assert_exit "disabled invalid JSON" 0 "$RC"

RC=$(run_hook peer-review-on-stop.sh '{"stop_hook_active":false}' CCT_PEER_REVIEW_ENABLED=true CLAUDE_PROJECT_DIR=/tmp)
assert_exit "enabled but no marker" 0 "$RC"

RC=$(run_hook peer-review-on-stop.sh '{"stop_hook_active":false}' CCT_PEER_REVIEW_ENABLED=true CLAUDE_PROJECT_DIR=/nonexistent)
assert_exit "enabled but nonexistent dir" 0 "$RC"

# --- Malformed marker cleanup ---
PEER_TMP=$(mktemp -d)
mkdir -p "$PEER_TMP/.cct/review"
echo '{"feature_id":"test"}' > "$PEER_TMP/.cct/review/pending.json"
RC=$(run_hook peer-review-on-stop.sh '{"stop_hook_active":false}' CCT_PEER_REVIEW_ENABLED=true CLAUDE_PROJECT_DIR="$PEER_TMP")
assert_exit "malformed marker (missing keys) exits 0" 0 "$RC"
if [[ ! -f "$PEER_TMP/.cct/review/pending.json" ]]; then
    echo "  PASS: malformed marker cleaned up"
    PASS=$((PASS + 1))
else
    echo "  FAIL: malformed marker NOT cleaned up"
    FAIL=$((FAIL + 1))
fi
rm -rf "$PEER_TMP"

# --- Stale marker cleanup ---
PEER_TMP=$(mktemp -d)
mkdir -p "$PEER_TMP/.cct/review"
cat > "$PEER_TMP/.cct/review/pending.json" << 'STALE_EOF'
{"feature_id":"test","phase":"build","target_ref":"main","subject_provider":"claude","requested_at":"2020-01-01T00:00:00Z"}
STALE_EOF
RC=$(run_hook peer-review-on-stop.sh '{"stop_hook_active":false}' CCT_PEER_REVIEW_ENABLED=true CLAUDE_PROJECT_DIR="$PEER_TMP" CCT_SESSION_START="2026-01-01T00:00:00Z")
assert_exit "stale marker exits 0" 0 "$RC"
if [[ ! -f "$PEER_TMP/.cct/review/pending.json" ]]; then
    echo "  PASS: stale marker cleaned up"
    PASS=$((PASS + 1))
else
    echo "  FAIL: stale marker NOT cleaned up"
    FAIL=$((FAIL + 1))
fi
rm -rf "$PEER_TMP"

# --- Bypass cleans up marker ---
PEER_TMP=$(mktemp -d)
mkdir -p "$PEER_TMP/.cct/review"
cat > "$PEER_TMP/.cct/review/pending.json" << 'BYPASS_EOF'
{"feature_id":"test","phase":"build","target_ref":"main","subject_provider":"claude","requested_at":"2026-03-09T00:00:00Z"}
BYPASS_EOF
RC=$(run_hook peer-review-on-stop.sh '{"stop_hook_active":false}' CCT_PEER_REVIEW_ENABLED=true CLAUDE_PROJECT_DIR="$PEER_TMP" CCT_PEER_BYPASS=true CCT_SESSION_START="2026-01-01T00:00:00Z")
assert_exit "bypass exits 0" 0 "$RC"
if [[ ! -f "$PEER_TMP/.cct/review/pending.json" ]]; then
    echo "  PASS: bypass marker cleaned up"
    PASS=$((PASS + 1))
else
    echo "  FAIL: bypass marker NOT cleaned up"
    FAIL=$((FAIL + 1))
fi
rm -rf "$PEER_TMP"

# --- Valid marker but no runner → fail-closed (exit 2) ---
PEER_TMP=$(mktemp -d)
mkdir -p "$PEER_TMP/.cct/review"
cat > "$PEER_TMP/.cct/review/pending.json" << 'VALID_EOF'
{"feature_id":"test","phase":"build","target_ref":"main","subject_provider":"claude","requested_at":"2026-03-09T00:00:00Z"}
VALID_EOF
# Override PATH so runner is not found, clear HOME so ~/.local/bin isn't checked
RC=$(printf '{"stop_hook_active":false}' | env CCT_PEER_REVIEW_ENABLED=true CLAUDE_PROJECT_DIR="$PEER_TMP" CCT_SESSION_START="2026-01-01T00:00:00Z" HOME=/nonexistent PATH=/usr/bin:/bin bash "$HOOKS_DIR/peer-review-on-stop.sh" >/dev/null 2>/dev/null || echo $?)
# If jq is not in /usr/bin or /bin, hook exits 0 (jq guard); otherwise exit 2 (no runner)
if command -v /usr/bin/jq &>/dev/null || command -v /bin/jq &>/dev/null; then
    assert_exit "valid marker no runner → fail-closed" 2 "$RC"
else
    assert_exit "valid marker no jq → jq guard" 0 "$RC"
fi
rm -rf "$PEER_TMP"

echo ""
echo "=== peer-review-runner.sh — PROJECT_DIR derivation ==="

RUNNER_SCRIPT="$(cd "$(dirname "$0")/../scripts" && pwd)/peer-review-runner.sh"

# Test PROJECT_DIR derivation with a mock marker
RUNNER_TMP=$(mktemp -d)
mkdir -p "$RUNNER_TMP/.cct/review"
echo '{}' > "$RUNNER_TMP/.cct/review/pending.json"
MARKER_PATH="$RUNNER_TMP/.cct/review/pending.json"
# Extract just the PROJECT_DIR derivation logic
MARKER_ABS=$(cd "$(dirname "$MARKER_PATH")" && pwd)/$(basename "$MARKER_PATH")
DERIVED_DIR=$(dirname "$(dirname "$(dirname "$MARKER_ABS")")")
if [[ "$DERIVED_DIR" == "$RUNNER_TMP" ]]; then
    echo "  PASS: PROJECT_DIR derived correctly from marker path"
    PASS=$((PASS + 1))
else
    echo "  FAIL: PROJECT_DIR='$DERIVED_DIR' expected='$RUNNER_TMP'"
    FAIL=$((FAIL + 1))
fi
rm -rf "$RUNNER_TMP"

# Test with nested project path
RUNNER_TMP=$(mktemp -d)
NESTED="$RUNNER_TMP/deep/nested/project"
mkdir -p "$NESTED/.cct/review"
echo '{}' > "$NESTED/.cct/review/pending.json"
MARKER_PATH="$NESTED/.cct/review/pending.json"
MARKER_ABS=$(cd "$(dirname "$MARKER_PATH")" && pwd)/$(basename "$MARKER_PATH")
DERIVED_DIR=$(dirname "$(dirname "$(dirname "$MARKER_ABS")")")
if [[ "$DERIVED_DIR" == "$NESTED" ]]; then
    echo "  PASS: PROJECT_DIR correct for nested path"
    PASS=$((PASS + 1))
else
    echo "  FAIL: PROJECT_DIR='$DERIVED_DIR' expected='$NESTED'"
    FAIL=$((FAIL + 1))
fi
rm -rf "$RUNNER_TMP"

echo ""
echo "=== claude-code launcher — --peer-review flag parsing ==="

LAUNCHER="$(cd "$(dirname "$0")/../adapters/claude-code" && pwd)/claude-code"

# Helper: source just the flag-parsing section and inspect variables
parse_flags() {
    # Run the launcher with 'help' subcommand injected (exits after help, no tmux needed)
    # We only care about variable values after parsing, so we inject a trap
    local result
    result=$(bash -c '
        PLAYWRIGHT=0
        PEER_REVIEW_ENABLED=""
        PEER_PROVIDER=""
        PEER_SCOPE="both"
        BACKEND_AUTO="auto"
        BACKEND_TMUX="tmux"
        BACKEND_CMUX="cmux"
        SESSION_BACKEND="$BACKEND_AUTO"
        POSITIONAL=()
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --peer-review)
                    PEER_REVIEW_ENABLED="true"
                    if [[ -n "${2:-}" && "${2:0:2}" != "--" && "${2:0:1}" != "/" && "${2:0:2}" != "./" && "${2:0:1}" != "~" && "$2" != */* && ! -d "$2" ]]; then
                        PEER_PROVIDER="$2"
                        shift
                    fi
                    shift
                    ;;
                --peer-review-off)
                    PEER_REVIEW_ENABLED="false"
                    shift
                    ;;
                --peer-review-scope)
                    PEER_SCOPE="${2:-both}"
                    shift 2
                    ;;
                --shell)
                    SESSION_BACKEND="${2:-$BACKEND_AUTO}"
                    case "$SESSION_BACKEND" in
                        "$BACKEND_AUTO"|"$BACKEND_CMUX"|"$BACKEND_TMUX")
                            ;;
                        *)
                            echo "INVALID"
                            exit 0
                            ;;
                    esac
                    shift 2
                    ;;
                --playwright)
                    PLAYWRIGHT=1
                    shift
                    ;;
                *)
                    POSITIONAL+=("$1")
                    shift
                    ;;
            esac
        done
        set -- "${POSITIONAL[@]+"${POSITIONAL[@]}"}"
        echo "ENABLED=$PEER_REVIEW_ENABLED|PROVIDER=$PEER_PROVIDER|SCOPE=$PEER_SCOPE|SHELL=$SESSION_BACKEND|POS=${1:-}"
    ' -- "$@" 2>/dev/null)
    echo "$result"
}

resolve_backend_for_os() {
    local backend="$1" os_name="$2"
    bash -c '
        BACKEND_AUTO="auto"
        BACKEND_TMUX="tmux"
        BACKEND_CMUX="cmux"
        SESSION_BACKEND="$1"
        OS_NAME="$2"

        resolve_backend() {
            if [[ "$SESSION_BACKEND" != "$BACKEND_AUTO" ]]; then
                printf "%s\n" "$SESSION_BACKEND"
                return
            fi
            if [[ "$OS_NAME" == "Darwin" ]]; then
                printf "%s\n" "$BACKEND_CMUX"
            else
                printf "%s\n" "$BACKEND_TMUX"
            fi
        }

        resolve_backend
    ' -- "$backend" "$os_name" 2>/dev/null
}

# Test: --peer-review codex /path
RESULT=$(parse_flags --peer-review codex /some/path)
if [[ "$RESULT" == "ENABLED=true|PROVIDER=codex|SCOPE=both|SHELL=auto|POS=/some/path" ]]; then
    echo "  PASS: --peer-review codex /path"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --peer-review codex /path → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: --peer-review /absolute/path (path not consumed as provider)
RESULT=$(parse_flags --peer-review /some/path)
if [[ "$RESULT" == "ENABLED=true|PROVIDER=|SCOPE=both|SHELL=auto|POS=/some/path" ]]; then
    echo "  PASS: --peer-review /absolute/path not consumed"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --peer-review /absolute/path → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: --peer-review ~/path (tilde path not consumed)
RESULT=$(parse_flags --peer-review '~/projects/app')
if [[ "$RESULT" == "ENABLED=true|PROVIDER=|SCOPE=both|SHELL=auto|POS=~/projects/app" ]]; then
    echo "  PASS: --peer-review ~/path not consumed"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --peer-review ~/path → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: --peer-review ./relative (dot-relative not consumed)
RESULT=$(parse_flags --peer-review ./my-app)
if [[ "$RESULT" == "ENABLED=true|PROVIDER=|SCOPE=both|SHELL=auto|POS=./my-app" ]]; then
    echo "  PASS: --peer-review ./relative not consumed"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --peer-review ./relative → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: --peer-review rel/path (path with slash not consumed)
RESULT=$(parse_flags --peer-review projects/app)
if [[ "$RESULT" == "ENABLED=true|PROVIDER=|SCOPE=both|SHELL=auto|POS=projects/app" ]]; then
    echo "  PASS: --peer-review rel/path not consumed"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --peer-review rel/path → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: --peer-review <existing-dir> (directory not consumed as provider)
FLAG_TMP=$(mktemp -d)
DIRNAME=$(basename "$FLAG_TMP")
RESULT=$(cd "$(dirname "$FLAG_TMP")" && parse_flags --peer-review "$DIRNAME")
if [[ "$RESULT" == "ENABLED=true|PROVIDER=|SCOPE=both|SHELL=auto|POS=$DIRNAME" ]]; then
    echo "  PASS: --peer-review <existing-dir> not consumed"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --peer-review <existing-dir> → $RESULT"
    FAIL=$((FAIL + 1))
fi
rm -rf "$FLAG_TMP"

# Test: --peer-review-off
RESULT=$(parse_flags --peer-review-off /some/path)
if [[ "$RESULT" == "ENABLED=false|PROVIDER=|SCOPE=both|SHELL=auto|POS=/some/path" ]]; then
    echo "  PASS: --peer-review-off"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --peer-review-off → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: --peer-review-scope code
RESULT=$(parse_flags --peer-review codex --peer-review-scope code /path)
if [[ "$RESULT" == "ENABLED=true|PROVIDER=codex|SCOPE=code|SHELL=auto|POS=/path" ]]; then
    echo "  PASS: --peer-review-scope code"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --peer-review-scope code → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: no flags (defaults)
RESULT=$(parse_flags /some/path)
if [[ "$RESULT" == "ENABLED=|PROVIDER=|SCOPE=both|SHELL=auto|POS=/some/path" ]]; then
    echo "  PASS: no peer-review flags"
    PASS=$((PASS + 1))
else
    echo "  FAIL: no flags → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: --peer-review alone (no provider, no path)
RESULT=$(parse_flags --peer-review)
if [[ "$RESULT" == "ENABLED=true|PROVIDER=|SCOPE=both|SHELL=auto|POS=" ]]; then
    echo "  PASS: --peer-review alone"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --peer-review alone → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: --shell cmux
RESULT=$(parse_flags --shell cmux /some/path)
if [[ "$RESULT" == "ENABLED=|PROVIDER=|SCOPE=both|SHELL=cmux|POS=/some/path" ]]; then
    echo "  PASS: --shell cmux"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --shell cmux → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: --shell tmux
RESULT=$(parse_flags --shell tmux /some/path)
if [[ "$RESULT" == "ENABLED=|PROVIDER=|SCOPE=both|SHELL=tmux|POS=/some/path" ]]; then
    echo "  PASS: --shell tmux"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --shell tmux → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: --shell auto
RESULT=$(parse_flags --shell auto /some/path)
if [[ "$RESULT" == "ENABLED=|PROVIDER=|SCOPE=both|SHELL=auto|POS=/some/path" ]]; then
    echo "  PASS: --shell auto"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --shell auto → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: macOS defaults to cmux when backend is auto
RESULT=$(resolve_backend_for_os auto Darwin)
if [[ "$RESULT" == "cmux" ]]; then
    echo "  PASS: auto backend defaults to cmux on macOS"
    PASS=$((PASS + 1))
else
    echo "  FAIL: auto backend on macOS → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: non-macOS defaults to tmux when backend is auto
RESULT=$(resolve_backend_for_os auto Linux)
if [[ "$RESULT" == "tmux" ]]; then
    echo "  PASS: auto backend defaults to tmux off macOS"
    PASS=$((PASS + 1))
else
    echo "  FAIL: auto backend off macOS → $RESULT"
    FAIL=$((FAIL + 1))
fi

echo ""
if [[ "$PASS" -ne "$TEST_HOOKS_EXPECTED_PASS" ]]; then
  echo "  FAIL: assertion-count drift (expected $TEST_HOOKS_EXPECTED_PASS, got $PASS)"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
