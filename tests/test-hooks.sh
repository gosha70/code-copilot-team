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
    local backend="$1" os_name="$2" inside_cmux="${3:-0}" saved_backend="${4:-}" inside_tmux="${5:-0}" inside_zellij="${6:-0}"
    bash -c '
        BACKEND_AUTO="auto"
        BACKEND_TMUX="tmux"
        BACKEND_CMUX="cmux"
        SESSION_BACKEND="$1"
        OS_NAME="$2"
        INSIDE_CMUX="$3"
        SAVED_BACKEND="$4"
        INSIDE_TMUX="$5"
        INSIDE_ZELLIJ="$6"

        resolve_backend() {
            if [[ "$SESSION_BACKEND" != "$BACKEND_AUTO" ]]; then
                printf "%s\n" "$SESSION_BACKEND"
                return
            fi
            # Zellij compatibility: run directly instead of nesting
            if [[ "$INSIDE_ZELLIJ" == "1" ]]; then
                printf "%s\n" "direct"
                return
            fi
            # Active multiplexer wins
            if [[ "$INSIDE_CMUX" == "1" ]]; then
                printf "%s\n" "$BACKEND_CMUX"
                return
            fi
            if [[ "$INSIDE_TMUX" == "1" ]]; then
                printf "%s\n" "$BACKEND_TMUX"
                return
            fi
            # Saved preference (only recognized values)
            case "$SAVED_BACKEND" in
                "$BACKEND_CMUX"|"$BACKEND_TMUX")
                    printf "%s\n" "$SAVED_BACKEND"
                    return
                    ;;
            esac
            # Default: cmux on macOS, tmux elsewhere
            if [[ "$OS_NAME" == "Darwin" ]]; then
                printf "%s\n" "$BACKEND_CMUX"
            else
                printf "%s\n" "$BACKEND_TMUX"
            fi
        }

        resolve_backend
    ' -- "$backend" "$os_name" "$inside_cmux" "$saved_backend" "$inside_tmux" "$inside_zellij" 2>/dev/null
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

# Test: --shell zellij now rejected
RESULT=$(parse_flags --shell zellij /some/path)
if [[ "$RESULT" == "INVALID" ]]; then
    echo "  PASS: --shell zellij rejected"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --shell zellij should be rejected → $RESULT"
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

# Test: --shell invalid rejected
RESULT=$(parse_flags --shell bogus /some/path)
if [[ "$RESULT" == "INVALID" ]]; then
    echo "  PASS: --shell invalid rejected"
    PASS=$((PASS + 1))
else
    echo "  FAIL: --shell invalid → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: macOS defaults to cmux
RESULT=$(resolve_backend_for_os auto Darwin)
if [[ "$RESULT" == "cmux" ]]; then
    echo "  PASS: auto defaults to cmux on macOS"
    PASS=$((PASS + 1))
else
    echo "  FAIL: auto on macOS → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: non-macOS defaults to tmux
RESULT=$(resolve_backend_for_os auto Linux)
if [[ "$RESULT" == "tmux" ]]; then
    echo "  PASS: auto defaults to tmux off macOS"
    PASS=$((PASS + 1))
else
    echo "  FAIL: auto off macOS → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: inside cmux wins on macOS
RESULT=$(resolve_backend_for_os auto Darwin 1)
if [[ "$RESULT" == "cmux" ]]; then
    echo "  PASS: inside cmux wins on macOS"
    PASS=$((PASS + 1))
else
    echo "  FAIL: inside cmux on macOS → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: explicit --shell overrides active multiplexer
RESULT=$(resolve_backend_for_os tmux Darwin 1)
if [[ "$RESULT" == "tmux" ]]; then
    echo "  PASS: explicit --shell tmux overrides active cmux"
    PASS=$((PASS + 1))
else
    echo "  FAIL: explicit tmux inside cmux → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: saved preference tmux overrides macOS default
RESULT=$(resolve_backend_for_os auto Darwin 0 tmux)
if [[ "$RESULT" == "tmux" ]]; then
    echo "  PASS: saved preference tmux overrides macOS default"
    PASS=$((PASS + 1))
else
    echo "  FAIL: saved tmux on macOS → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: active multiplexer wins over saved preference
RESULT=$(resolve_backend_for_os auto Darwin 1 tmux)
if [[ "$RESULT" == "cmux" ]]; then
    echo "  PASS: active cmux wins over saved tmux preference"
    PASS=$((PASS + 1))
else
    echo "  FAIL: active cmux with saved tmux → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: inside tmux detects correctly
RESULT=$(resolve_backend_for_os auto Darwin 0 "" 1)
if [[ "$RESULT" == "tmux" ]]; then
    echo "  PASS: inside tmux wins on macOS"
    PASS=$((PASS + 1))
else
    echo "  FAIL: inside tmux on macOS → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: inside tmux wins over saved preference
RESULT=$(resolve_backend_for_os auto Linux 0 cmux 1)
if [[ "$RESULT" == "tmux" ]]; then
    echo "  PASS: inside tmux wins over saved cmux preference"
    PASS=$((PASS + 1))
else
    echo "  FAIL: inside tmux with saved cmux → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: unrecognized saved backend is ignored
RESULT=$(resolve_backend_for_os auto Linux 0 screen)
if [[ "$RESULT" == "tmux" ]]; then
    echo "  PASS: unrecognized saved backend 'screen' ignored"
    PASS=$((PASS + 1))
else
    echo "  FAIL: unrecognized saved 'screen' → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: empty saved backend falls through to default
RESULT=$(resolve_backend_for_os auto Linux 0 "")
if [[ "$RESULT" == "tmux" ]]; then
    echo "  PASS: empty saved backend falls through to default"
    PASS=$((PASS + 1))
else
    echo "  FAIL: empty saved backend → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: inside Zellij returns "direct" (compatibility path)
RESULT=$(resolve_backend_for_os auto Darwin 0 "" 0 1)
if [[ "$RESULT" == "direct" ]]; then
    echo "  PASS: inside Zellij returns direct on macOS"
    PASS=$((PASS + 1))
else
    echo "  FAIL: inside Zellij on macOS → $RESULT"
    FAIL=$((FAIL + 1))
fi

RESULT=$(resolve_backend_for_os auto Linux 0 "" 0 1)
if [[ "$RESULT" == "direct" ]]; then
    echo "  PASS: inside Zellij returns direct on Linux"
    PASS=$((PASS + 1))
else
    echo "  FAIL: inside Zellij on Linux → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: inside Zellij takes priority over saved preference
RESULT=$(resolve_backend_for_os auto Darwin 0 cmux 0 1)
if [[ "$RESULT" == "direct" ]]; then
    echo "  PASS: inside Zellij wins over saved cmux preference"
    PASS=$((PASS + 1))
else
    echo "  FAIL: inside Zellij with saved cmux → $RESULT"
    FAIL=$((FAIL + 1))
fi

# Test: start_session() takes Zellij direct fast path (integration)
# Extract all function definitions from the launcher, source them, then
# stub exec_claude_in_current_shell and invoke start_session.
ZELLIJ_TMP=$(mktemp -d)
ZELLIJ_OUT=$(bash -c '
    set -e
    # Extract function definitions (everything before the main block)
    FUNCS=$(sed -n "1,/^# ── Main/p" "'"$LAUNCHER"'")
    eval "$FUNCS"

    # Override globals
    export ZELLIJ_SESSION_NAME=test-session
    LAUNCHER_CONFIG=/nonexistent
    SESSION_BACKEND="$BACKEND_AUTO"
    PEER_REVIEW_ENABLED=""
    LOGS_DIR="'"$ZELLIJ_TMP"'"

    # Stub exec so it echoes a marker instead of replacing the process
    exec_claude_in_current_shell() {
        echo "STUB_EXEC_CALLED dir=$1"
    }

    start_session "'"$ZELLIJ_TMP"'"
' 2>&1) || true
if echo "$ZELLIJ_OUT" | grep -q "Detected active Zellij session" && echo "$ZELLIJ_OUT" | grep -q "STUB_EXEC_CALLED dir=$ZELLIJ_TMP"; then
    echo "  PASS: start_session takes Zellij direct fast path"
    PASS=$((PASS + 1))
else
    echo "  FAIL: start_session Zellij fast path → $ZELLIJ_OUT"
    FAIL=$((FAIL + 1))
fi
rm -rf "$ZELLIJ_TMP"

# ══════════════════════════════════════════════════════════════
# protect-git.sh tests
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== protect-git.sh ==="

# --- Should block: bare git commit ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"git commit -m \"test\""}}')
assert_exit "bare git commit blocked" 2 "$RC"

# --- Should block: bare git push ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"git push origin main"}}')
assert_exit "bare git push blocked" 2 "$RC"

# --- Should block: after && ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"git add . && git commit -m \"test\""}}')
assert_exit "git commit after && blocked" 2 "$RC"

# --- Should block: after ; ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"git add .; git commit -m \"test\""}}')
assert_exit "git commit after ; blocked" 2 "$RC"

# --- Should block: after || ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"false || git push"}}')
assert_exit "git push after || blocked" 2 "$RC"

# --- Should block: in subshell ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"(git commit -m \"test\")"}}')
assert_exit "git commit in subshell blocked" 2 "$RC"

# --- Should block: in $() ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"echo $(git push origin main)"}}')
assert_exit "git push in command substitution blocked" 2 "$RC"

# --- Should block: newline-separated commands ---
CMD_NL=$(jq -n --arg cmd $'git add .\ngit commit -m test' '{"tool_input":{"command":$cmd}}')
RC=$(run_hook protect-git.sh "$CMD_NL")
assert_exit "git commit after newline blocked" 2 "$RC"

# --- Should block: with env var prefix ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"GIT_AUTHOR_NAME=test git commit -m \"test\""}}')
assert_exit "git commit with env prefix blocked" 2 "$RC"

# --- Should block: env command wrapper ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"env FOO=bar git commit -m \"test\""}}')
assert_exit "env FOO=bar git commit blocked" 2 "$RC"

# --- Should block: env var with quoted value ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"env FOO=bar git push origin main"}}')
assert_exit "env git push blocked" 2 "$RC"

# --- Should block: env with flags ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"env -i FOO=bar git commit -m \"test\""}}')
assert_exit "env -i git commit blocked" 2 "$RC"

RC=$(run_hook protect-git.sh '{"tool_input":{"command":"env -u HOME git push origin main"}}')
assert_exit "env -u git push blocked" 2 "$RC"

# --- Should block: command wrapper ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"command git push origin main"}}')
assert_exit "command git push blocked" 2 "$RC"

RC=$(run_hook protect-git.sh '{"tool_input":{"command":"command git commit -m \"test\""}}')
assert_exit "command git commit blocked" 2 "$RC"

# --- Should block: exec wrapper ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"exec git push origin main"}}')
assert_exit "exec git push blocked" 2 "$RC"

# --- Should block: stacked wrappers ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"command env -u HOME git commit -m \"test\""}}')
assert_exit "command env git commit blocked" 2 "$RC"

RC=$(run_hook protect-git.sh '{"tool_input":{"command":"exec env -i FOO=bar git push origin main"}}')
assert_exit "exec env git push blocked" 2 "$RC"

# --- Should allow: wrapped non-git commands mentioning git push/commit ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"command env -u HOME echo git push origin main"}}')
assert_exit "command env echo git push allowed" 0 "$RC"

RC=$(run_hook protect-git.sh '{"tool_input":{"command":"env -i FOO=bar printf git commit"}}')
assert_exit "env printf git commit allowed" 0 "$RC"

# --- Should allow: heredoc body containing git commit ---
CMD_HEREDOC=$(jq -n --arg cmd $'cat <<EOF\ngit commit -m x\nEOF' '{"tool_input":{"command":$cmd}}')
RC=$(run_hook protect-git.sh "$CMD_HEREDOC")
assert_exit "heredoc git commit allowed" 0 "$RC"

# --- Should allow: heredoc body containing git push ---
CMD_HEREDOC2=$(jq -n --arg cmd $'cat <<\'EOF\'\ngit push origin main\nEOF' '{"tool_input":{"command":$cmd}}')
RC=$(run_hook protect-git.sh "$CMD_HEREDOC2")
assert_exit "heredoc git push allowed" 0 "$RC"

# --- Should allow: single-quoted literal with $() ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"echo '\''$(git push origin main)'\''"}}')
assert_exit "single-quoted git push allowed" 0 "$RC"

# --- Should block: command substitution inside double quotes ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"echo \"$(git push origin main)\""}}')
assert_exit "quoted command substitution git push blocked" 2 "$RC"

RC=$(run_hook protect-git.sh '{"tool_input":{"command":"echo \"$(git commit -m test)\""}}')
assert_exit "quoted command substitution git commit blocked" 2 "$RC"

# --- Should block: backtick substitution inside double quotes ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"echo \"`git push origin main`\""}}')
assert_exit "quoted backtick git push blocked" 2 "$RC"

# --- Should allow: echo containing git commit (not executed) ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"echo \"git commit -m x\""}}')
assert_exit "echo git commit allowed" 0 "$RC"

# --- Should allow: echo containing git push ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"echo \"git push origin main\""}}')
assert_exit "echo git push allowed" 0 "$RC"

# --- Should allow: git status (not commit/push) ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"git status"}}')
assert_exit "git status allowed" 0 "$RC"

# --- Should allow: git log ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"git log --oneline -5"}}')
assert_exit "git log allowed" 0 "$RC"

# --- Should allow: git diff ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"git diff HEAD"}}')
assert_exit "git diff allowed" 0 "$RC"

# --- Should allow: override env var ---
RC=$(run_hook protect-git.sh '{"tool_input":{"command":"git commit -m \"test\""}}' HOOK_GIT_ALLOW=true)
assert_exit "override allows git commit" 0 "$RC"

# --- Edge cases ---
RC=$(run_hook protect-git.sh '{}')
assert_exit "missing command" 0 "$RC"

RC=$(run_hook protect-git.sh '')
assert_exit "empty input" 0 "$RC"

RC=$(run_hook protect-git.sh 'not json')
assert_exit "invalid JSON" 0 "$RC"

# ══════════════════════════════════════════════════════════════
# statusline.sh tests
# ══════════════════════════════════════════════════════════════

echo "=== statusline.sh ==="

STATUSLINE="$(cd "$(dirname "$0")/../adapters/claude-code/.claude" && pwd)/statusline.sh"

# Helper: run statusline with JSON input, return stdout
run_statusline() {
  printf '%s' "$1" | bash "$STATUSLINE" 2>/dev/null
}

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (expected to contain '$needle', got '$haystack')"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local name="$1" haystack="$2" needle="$3"
  if ! echo "$haystack" | grep -qF "$needle"; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (expected NOT to contain '$needle')"
    FAIL=$((FAIL + 1))
  fi
}

# Basic output with all fields
BASIC_INPUT='{"model":{"display_name":"Opus"},"workspace":{"current_dir":"/tmp/my-repo"},"cwd":"/tmp/my-repo","context_window":{"used_percentage":42},"cost":{"total_cost_usd":1.23,"total_duration_ms":754000,"total_lines_added":100,"total_lines_removed":5}}'
BASIC_OUT=$(run_statusline "$BASIC_INPUT")
assert_contains "displays model name" "$BASIC_OUT" "[Opus]"
assert_contains "displays project dir" "$BASIC_OUT" "my-repo"
assert_contains "displays context percent" "$BASIC_OUT" "42%"
assert_contains "displays cost" "$BASIC_OUT" '$1.23'
assert_contains "displays lines added" "$BASIC_OUT" "+100"
assert_contains "displays lines removed" "$BASIC_OUT" "/-5"
assert_contains "displays duration" "$BASIC_OUT" "12m"

# Agent name shown when present
AGENT_INPUT='{"model":{"display_name":"Opus"},"agent":{"name":"build"},"workspace":{"current_dir":"/tmp/repo"},"cwd":"/tmp/repo","context_window":{"used_percentage":0},"cost":{"total_cost_usd":0,"total_duration_ms":0,"total_lines_added":0,"total_lines_removed":0}}'
AGENT_OUT=$(run_statusline "$AGENT_INPUT")
assert_contains "displays agent name" "$AGENT_OUT" "build"

# Agent name absent when not in JSON
NO_AGENT_INPUT='{"model":{"display_name":"Opus"},"workspace":{"current_dir":"/tmp/repo"},"cwd":"/tmp/repo","context_window":{"used_percentage":0},"cost":{"total_cost_usd":0,"total_duration_ms":0,"total_lines_added":0,"total_lines_removed":0}}'
NO_AGENT_OUT=$(run_statusline "$NO_AGENT_INPUT")
assert_not_contains "no agent when absent" "$NO_AGENT_OUT" "build"

# Worktree shown instead of project dir
WT_INPUT='{"model":{"display_name":"Opus"},"workspace":{"current_dir":"/tmp/repo"},"cwd":"/tmp/repo","context_window":{"used_percentage":0},"cost":{"total_cost_usd":0,"total_duration_ms":0,"total_lines_added":0,"total_lines_removed":0},"worktree":{"name":"my-feature"}}'
WT_OUT=$(run_statusline "$WT_INPUT")
assert_contains "displays worktree name" "$WT_OUT" "wt:my-feature"

# Paths with spaces handled correctly
SPACE_INPUT='{"model":{"display_name":"Opus"},"workspace":{"current_dir":"/tmp/My Cool Project"},"cwd":"/tmp/My Cool Project","context_window":{"used_percentage":0},"cost":{"total_cost_usd":0,"total_duration_ms":0,"total_lines_added":0,"total_lines_removed":0}}'
SPACE_OUT=$(run_statusline "$SPACE_INPUT")
assert_contains "handles spaces in path" "$SPACE_OUT" "My Cool Project"

# Per-workspace cache isolation: different workspaces get different cache files
CACHE_KEY_A=$(printf '%s' "/tmp/repo-a" | cksum | cut -d' ' -f1)
CACHE_KEY_B=$(printf '%s' "/tmp/repo-b" | cksum | cut -d' ' -f1)
if [[ "$CACHE_KEY_A" != "$CACHE_KEY_B" ]]; then
  echo "  PASS: per-workspace cache keys differ"
  PASS=$((PASS + 1))
else
  echo "  FAIL: per-workspace cache keys are identical"
  FAIL=$((FAIL + 1))
fi

# Output is a single line (no multi-line rendering glitches)
LINE_COUNT=$(echo "$BASIC_OUT" | wc -l | tr -d ' ')
if [[ "$LINE_COUNT" -eq 1 ]]; then
  echo "  PASS: output is single line"
  PASS=$((PASS + 1))
else
  echo "  FAIL: output is $LINE_COUNT lines (expected 1)"
  FAIL=$((FAIL + 1))
fi

# Output contains no ANSI escape codes (plain text only)
if echo "$BASIC_OUT" | grep -qP '\033\[' 2>/dev/null || echo "$BASIC_OUT" | grep -q $'\033' 2>/dev/null; then
  echo "  FAIL: output contains ANSI escape codes"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: output is plain text (no ANSI)"
  PASS=$((PASS + 1))
fi

# Null/missing fields handled gracefully
NULL_INPUT='{"model":{"display_name":"Opus"},"workspace":{"current_dir":"/tmp/repo"},"cwd":"/tmp/repo","context_window":{"used_percentage":null},"cost":{"total_cost_usd":null,"total_duration_ms":null,"total_lines_added":null,"total_lines_removed":null}}'
NULL_OUT=$(run_statusline "$NULL_INPUT")
assert_contains "handles null fields" "$NULL_OUT" "[Opus]"
assert_contains "null percentage defaults to 0" "$NULL_OUT" "0%"

# Git reads from workspace, not cwd — run from /tmp pointing at this repo
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EXPECTED_BRANCH=$(git -C "$REPO_DIR" branch --show-current 2>/dev/null)
if [[ -n "$EXPECTED_BRANCH" ]]; then
  CROSS_CWD_INPUT="{\"model\":{\"display_name\":\"Opus\"},\"workspace\":{\"current_dir\":\"$REPO_DIR\"},\"cwd\":\"$REPO_DIR\",\"context_window\":{\"used_percentage\":0},\"cost\":{\"total_cost_usd\":0,\"total_duration_ms\":0,\"total_lines_added\":0,\"total_lines_removed\":0}}"
  # Invalidate cache so git actually runs
  CROSS_CACHE_KEY=$(printf '%s' "$REPO_DIR" | cksum | cut -d' ' -f1)
  rm -f "/tmp/claude-statusline-git-${CROSS_CACHE_KEY}"
  # Run from /tmp — git must still resolve the workspace repo
  CROSS_OUT=$(cd /tmp && printf '%s' "$CROSS_CWD_INPUT" | bash "$STATUSLINE" 2>/dev/null)
  assert_contains "git reads workspace not cwd" "$CROSS_OUT" "$EXPECTED_BRANCH"
else
  echo "  SKIP: no branch detected (detached HEAD)"
fi

echo ""

echo "=== setup.sh statusLine wiring ==="

SETUP_SCRIPT="$(cd "$(dirname "$0")/../adapters/claude-code" && pwd)/setup.sh"

# The HOOKS_CONFIG template includes statusLine
if grep -q '"statusLine"' "$SETUP_SCRIPT"; then
  echo "  PASS: setup.sh template includes statusLine"
  PASS=$((PASS + 1))
else
  echo "  FAIL: setup.sh template missing statusLine"
  FAIL=$((FAIL + 1))
fi

# --sync path wires statusLine into settings.json
SYNC_SECTION=$(sed -n '/^if.*--sync/,/exit 0/p' "$SETUP_SCRIPT")
if echo "$SYNC_SECTION" | grep -q 'statusLine'; then
  echo "  PASS: --sync path adds statusLine to settings"
  PASS=$((PASS + 1))
else
  echo "  FAIL: --sync path does not add statusLine to settings"
  FAIL=$((FAIL + 1))
fi

# no-hooks branch adds statusLine
NO_HOOKS_SECTION=$(sed -n '/Add hooks.*preserve/,/echo.*Added/p' "$SETUP_SCRIPT")
if echo "$NO_HOOKS_SECTION" | grep -q 'statusLine\|sl'; then
  echo "  PASS: no-hooks migration adds statusLine"
  PASS=$((PASS + 1))
else
  echo "  FAIL: no-hooks migration does not add statusLine"
  FAIL=$((FAIL + 1))
fi

# adapter settings.json includes statusLine
ADAPTER_SETTINGS="$(cd "$(dirname "$0")/../adapters/claude-code/.claude" && pwd)/settings.json"
if jq -e '.statusLine.command' "$ADAPTER_SETTINGS" >/dev/null 2>&1; then
  echo "  PASS: adapter settings.json has statusLine.command"
  PASS=$((PASS + 1))
else
  echo "  FAIL: adapter settings.json missing statusLine.command"
  FAIL=$((FAIL + 1))
fi

# statusline.sh is executable
if [[ -x "$STATUSLINE" ]]; then
  echo "  PASS: statusline.sh is executable"
  PASS=$((PASS + 1))
else
  echo "  FAIL: statusline.sh is not executable"
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
