#!/usr/bin/env bash
# test-claude-code-launcher.sh — #195: the branded launcher's headless
# passthrough and autonomous `build` entry, plus the driver's branded
# default. All claude invocations are mocked; no cmux/tmux, no network.
#
# Run from the repo root: bash tests/test-claude-code-launcher.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCHER="$REPO_DIR/adapters/claude-code/claude-code"

PASS=0; FAIL=0
assert_exit() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$actual" -eq "$expected" ]]; then PASS=$((PASS+1)); echo "  PASS: $name (exit $actual)";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected exit $expected, got $actual)"; fi
}
assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -qF -- "$needle"; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected to contain '$needle')"; fi
}
assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected '$expected', got '$actual')"; fi
}

# Mock claude: records argv + selected env, echoes a result marker,
# exits per MOCK_CLAUDE_RC. First on PATH for every launcher run.
MOCK_BIN=$(mktemp -d)
cat > "$MOCK_BIN/claude" << 'MOCK'
#!/usr/bin/env bash
{
    printf 'ARGV:'; printf ' %q' "$@"; printf '\n'
    printf 'BUN_OPTIONS:%s\n' "${BUN_OPTIONS:-}"
    printf 'PWD:%s\n' "$PWD"
} >> "${MOCK_CLAUDE_LOG:?}"
echo '{"subtype":"success","result":"mock headless output"}'
exit "${MOCK_CLAUDE_RC:-0}"
MOCK
chmod +x "$MOCK_BIN/claude"
# tmux/cmux canaries: if the launcher ever attaches a multiplexer in
# headless mode, these record the violation instead of hanging the suite.
for mux in tmux cmux; do
    cat > "$MOCK_BIN/$mux" << MOCK
#!/usr/bin/env bash
echo "MUX-VIOLATION:$mux \$*" >> "\${MUX_LOG:?}"
exit 0
MOCK
    chmod +x "$MOCK_BIN/$mux"
done

# Isolated HOME so ~/.claude/logs writes never touch the real one.
FAKE_HOME=$(mktemp -d)
run_launcher() {
    RC=0
    OUTPUT=$(cd "${RUN_DIR:-$REPO_DIR}" && \
        HOME="$FAKE_HOME" PATH="$MOCK_BIN:$PATH" \
        MOCK_CLAUDE_LOG="$CLAUDE_LOG" MUX_LOG="$MUX_LOG" \
        TMUX= CMUX_SESSION= \
        bash "$LAUNCHER" "$@" 2>&1) || RC=$?
}
new_logs() { CLAUDE_LOG=$(mktemp); MUX_LOG=$(mktemp); }

trap 'rm -rf "$MOCK_BIN" "$FAKE_HOME"' EXIT

echo "=== claude-code launcher tests (#195) ==="

# ── Headless passthrough ──
new_logs
run_launcher -p "build the thing" --output-format json --permission-mode acceptEdits --max-turns 10
assert_exit "headless -p invocation succeeds" 0 "$RC"
assert_contains "stdout is pure claude output" "$OUTPUT" "mock headless output"
assert_contains "all driver flags forwarded verbatim" "$(cat "$CLAUDE_LOG")" \
    "ARGV: -p build\\ the\\ thing --output-format json --permission-mode acceptEdits --max-turns 10"
assert_eq "no multiplexer attached in headless mode" "" "$(cat "$MUX_LOG")"
assert_contains "headless session inherits the BUN_OPTIONS ipv4 fix" \
    "$(cat "$CLAUDE_LOG")" "BUN_OPTIONS:--dns-result-order=ipv4first"
assert_eq "headless invocation recorded in the launcher log" "1" \
    "$(ls "$FAKE_HOME/.claude/logs/" | grep -c '^headless-')"

# -p's value is a PROMPT, never a project path (the pre-#195 failure).
new_logs
run_launcher -p "no/such/path shaped prompt" --output-format json
assert_exit "path-shaped prompt still runs headless" 0 "$RC"
assert_eq "prompt not consumed as a directory" "0" \
    "$(echo "$OUTPUT" | grep -c "does not exist")"

# --resume <id> before -p forwards verbatim (the driver's resume form).
new_logs
run_launcher --resume mock-session-1 -p "continue" --output-format json
assert_contains "resume id forwarded, not swallowed by wrapper parsing" \
    "$(cat "$CLAUDE_LOG")" "ARGV: --resume mock-session-1 -p continue --output-format json"

# Exit code fidelity: the driver branches on claude's exit code.
new_logs
MOCK_CLAUDE_RC=3 run_launcher -p "fail please" --output-format json
assert_exit "claude's exit code passes through untouched" 3 "$RC"

# --version probe (the driver's preflight) passes through.
new_logs
run_launcher --version
assert_exit "--version probe succeeds" 0 "$RC"
assert_contains "--version forwarded to claude" "$(cat "$CLAUDE_LOG")" "ARGV: --version"

# A -p AFTER a wrapper subcommand is that subcommand's business.
new_logs
run_launcher list
assert_eq "wrapper subcommand before -p is not hijacked" "0" \
    "$(grep -c 'ARGV' "$CLAUDE_LOG")"

# ── build subcommand ──
# Fixture "repo": a stub driver recording argv + CCT_PROJECT_DIR.
FAKE_REPO=$(mktemp -d)
mkdir -p "$FAKE_REPO/scripts"
DRIVER_LOG=$(mktemp)
cat > "$FAKE_REPO/scripts/auto-build-loop.sh" << STUB
#!/usr/bin/env bash
printf 'DRIVER-ARGV:%s\n' "\$*" >> "$DRIVER_LOG"
printf 'DRIVER-PROJECT:%s\n' "\${CCT_PROJECT_DIR:-}" >> "$DRIVER_LOG"
exit 0
STUB
PROJ=$(mktemp -d)
new_logs
RUN_DIR="$PROJ" CCT_REPO_DIR="$FAKE_REPO" run_launcher build demo-feat --profile pr --dry-run
assert_exit "build subcommand delegates to the driver" 0 "$RC"
assert_contains "feature id and driver flags forwarded" "$(cat "$DRIVER_LOG")" \
    "DRIVER-ARGV:demo-feat --profile pr --dry-run"
assert_contains "CCT_PROJECT_DIR is the invoking project" "$(cat "$DRIVER_LOG")" \
    "DRIVER-PROJECT:$PROJ"
assert_eq "build never touches claude directly" "0" "$(grep -c 'ARGV' "$CLAUDE_LOG")"
assert_eq "build never attaches a multiplexer" "" "$(cat "$MUX_LOG")"
assert_eq "no --dangerously-skip-permissions anywhere in the new paths" "0" \
    "$(grep -c 'dangerously-skip-permissions' "$DRIVER_LOG" "$CLAUDE_LOG" | awk -F: '{s+=$2} END {print s}')"

# Repo resolution failure is a hard, named error.
new_logs
RUN_DIR="$PROJ" CCT_REPO_DIR="/nonexistent-cct-repo" run_launcher build demo-feat
assert_exit "unresolvable repo is a hard error" 1 "$RC"
assert_contains "error names both remedies" "$OUTPUT" "CCT_REPO_DIR"

# Walk-up fallback: running from inside the real repo needs no env/bake.
new_logs
REAL_DRIVER_HIT=$(mktemp -u)
# Use a nested fixture repo so the real driver is never executed.
NESTED="$FAKE_REPO/deep/inner"
mkdir -p "$NESTED"
RUN_DIR="$NESTED" run_launcher build demo-feat --dry-run
assert_exit "walk-up finds the enclosing repo" 0 "$RC"
assert_contains "walk-up run reached the stub driver" "$(cat "$DRIVER_LOG")" \
    "DRIVER-PROJECT:$NESTED"

# ── Driver default (FR-1) ──
assert_contains "driver defaults CLAUDE_BIN to the branded launcher" \
    "$(grep 'CCT_CLAUDE_BIN:-' "$REPO_DIR/scripts/auto-build-loop.sh")" "claude-code"
assert_contains "PI backend default unchanged (symmetry)" \
    "$(grep 'CCT_PI_BIN:-' "$REPO_DIR/scripts/auto-build-loop.sh")" "pi-code"
assert_eq "setup.sh bakes the repo path at every install site" "3" \
    "$(grep -c '^\s*bake_launcher_repo_path$' "$REPO_DIR/adapters/claude-code/setup.sh")"

rm -rf "$FAKE_REPO" "$PROJ" "$DRIVER_LOG"

echo ""
echo "========================================="
echo "  claude-code launcher tests: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
