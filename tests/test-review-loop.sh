#!/usr/bin/env bash

# test-review-loop.sh — Comprehensive review loop integration tests
#
# Tests round trips, finding ID stability, stale-finding escalation,
# circuit breaker paths, read-only sandbox, dirty-worktree rejection,
# stop-hook validation, and monotonic round numbering across retries.
#
# Run from the repo root:
#   bash tests/test-review-loop.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$SCRIPT_DIR/../scripts/review-round-runner.sh"
HOOKS_DIR="$SCRIPT_DIR/../adapters/claude-code/.claude/hooks"
COUNTS_FILE="$SCRIPT_DIR/test-counts.env"
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

assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -q "$needle"; then
        echo "  PASS: $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $name (expected to contain '$needle')"
        FAIL=$((FAIL + 1))
    fi
}

assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  PASS: $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $name (expected '$expected', got '$actual')"
        FAIL=$((FAIL + 1))
    fi
}

# ── Test helpers ─────────────────────────────────────────────

# Create a mock provider profile at a given path
write_profile() {
    cat > "$1"
}

# Create a test project with git repo and review state
setup_project() {
    local dir
    dir=$(mktemp -d)
    git -C "$dir" init -q
    git -C "$dir" config user.email "test@test.local"
    git -C "$dir" config user.name "Test"
    mkdir -p "$dir/.cct/review" "$dir/specs/test-feat"
    echo "# Plan" > "$dir/specs/test-feat/plan.md"
    echo ".cct/" > "$dir/.gitignore"
    git -C "$dir" add -A
    git -C "$dir" commit -q -m "init"
    echo "$dir"
}

# Write state.json with defaults
write_state() {
    local dir="$1" round="${2:-0}" phase="${3:-build}"
    local now
    now=$(date +%s)
    cat > "$dir/.cct/review/state.json" << JSON
{"current_round": $round, "attempt": 1, "loop_start": $now, "feature_id": "test-feat", "phase": "$phase", "subject_provider": "claude", "peer_provider": "mock", "review_scope": "both", "target_ref": "main", "last_verdict": null, "findings": {}}
JSON
}

# Create a FAIL mock profile
FAIL_PROFILE=$(mktemp)
cat > "$FAIL_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Summary\nIssues found.\n\n### Findings\nFINDING|blocking|correctness|src/app.sh|near main|Missing error check|Add error handling\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML

# Create a PASS mock profile
PASS_PROFILE=$(mktemp)
cat > "$PASS_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Summary\nLooks good.\n\n### Findings\n\n### Verdict\nPASS\n'"
timeout_sec = 10
healthcheck = "true"
TOML

trap 'rm -f "$FAIL_PROFILE" "$PASS_PROFILE"' EXIT

# ══════════════════════════════════════════════════════════════
echo "=== Round trips ==="
# ══════════════════════════════════════════════════════════════

# Round 1: FAIL
P=$(setup_project)
write_state "$P" 0
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" 2>&1) || RC=$?
assert_exit "round 1 FAIL" 1 "$RC"

ROUND=$(jq -r '.current_round' "$P/.cct/review/state.json")
assert_eq "state round updated to 1" "1" "$ROUND"

VERDICT=$(jq -r '.verdict' "$P/.cct/review/findings-round-1.json")
assert_eq "findings-round-1 verdict is FAIL" "FAIL" "$VERDICT"

# Round 2: PASS (after simulated fix)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PASS_PROFILE" bash "$RUNNER" "$P" 2>&1) || RC=$?
assert_exit "round 2 PASS" 0 "$RC"

ROUND=$(jq -r '.current_round' "$P/.cct/review/state.json")
assert_eq "state round updated to 2" "2" "$ROUND"

if [[ -f "$P/.cct/review/loop-summary.json" ]]; then
    SUMMARY_VERDICT=$(jq -r '.verdict' "$P/.cct/review/loop-summary.json")
    assert_eq "loop-summary verdict is PASS" "PASS" "$SUMMARY_VERDICT"
else
    echo "  FAIL: loop-summary.json not created on PASS"
    FAIL=$((FAIL + 1))
fi
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Finding ID stability ==="
# ══════════════════════════════════════════════════════════════

# Same finding across rounds should produce the same ID
P=$(setup_project)
write_state "$P" 0
CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
ID_ROUND1=$(jq -r '.findings[0].id' "$P/.cct/review/findings-round-1.json")

CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
ID_ROUND2=$(jq -r '.findings[0].id' "$P/.cct/review/findings-round-2.json")

assert_eq "finding ID stable across rounds" "$ID_ROUND1" "$ID_ROUND2"

# ID should start with f- prefix
if [[ "$ID_ROUND1" == f-* ]]; then
    echo "  PASS: finding ID has f- prefix"
    PASS=$((PASS + 1))
else
    echo "  FAIL: finding ID missing f- prefix (got '$ID_ROUND1')"
    FAIL=$((FAIL + 1))
fi
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Circuit breaker: max rounds ==="
# ══════════════════════════════════════════════════════════════

P=$(setup_project)
write_state "$P" 0
# Run 5 rounds to hit the default limit
for i in 1 2 3 4 5; do
    CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
done

# Round 6 should trip the breaker
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" 2>&1) || RC=$?
assert_exit "max rounds breaker fires at round 6" 2 "$RC"

if [[ -f "$P/.cct/review/breaker-tripped.json" ]]; then
    BREAKER_TYPE=$(jq -r '.breaker' "$P/.cct/review/breaker-tripped.json")
    assert_eq "breaker type is max_rounds" "max_rounds" "$BREAKER_TYPE"
else
    echo "  FAIL: breaker-tripped.json not created"
    FAIL=$((FAIL + 1))
fi
rm -rf "$P"

# Custom max rounds via env var
P=$(setup_project)
write_state "$P" 0
CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
RC=0; OUTPUT=$(CCT_REVIEW_MAX_ROUNDS=2 CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" 2>&1) || RC=$?
assert_exit "custom max rounds (2) breaker fires at round 3" 2 "$RC"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Circuit breaker: wall-clock timeout ==="
# ══════════════════════════════════════════════════════════════

P=$(setup_project)
# Set loop_start far in the past to trigger timeout
PAST=$(($(date +%s) - 10000))
cat > "$P/.cct/review/state.json" << JSON
{"current_round": 1, "attempt": 1, "loop_start": $PAST, "feature_id": "test-feat", "phase": "build", "subject_provider": "claude", "peer_provider": "mock", "review_scope": "both", "target_ref": "main", "last_verdict": "FAIL", "findings": {}}
JSON
RC=0; OUTPUT=$(CCT_REVIEW_TIMEOUT_SEC=100 CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" 2>&1) || RC=$?
assert_exit "timeout breaker fires" 2 "$RC"
assert_contains "timeout breaker message" "$OUTPUT" "wall-clock timeout"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Circuit breaker: plan phase exempt ==="
# ══════════════════════════════════════════════════════════════

# Plan phase at round 6 should not trip max-rounds breaker
P=$(setup_project)
NOW=$(date +%s)
cat > "$P/.cct/review/state.json" << JSON
{"current_round": 5, "attempt": 1, "loop_start": $NOW, "feature_id": "test-feat", "phase": "plan", "subject_provider": "claude", "peer_provider": "mock", "review_scope": "both", "target_ref": "main", "last_verdict": "FAIL", "findings": {}}
JSON
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" 2>&1) || RC=$?
# Plan phase: should exit 0 (advisory), not 2 (breaker)
assert_exit "plan phase round 6 no breaker" 0 "$RC"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Dirty worktree rejection ==="
# ══════════════════════════════════════════════════════════════

P=$(setup_project)
write_state "$P" 0
echo "dirty" > "$P/untracked-file.txt"
git -C "$P" add "$P/untracked-file.txt"
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" 2>&1) || RC=$?
assert_exit "dirty worktree rejected" 1 "$RC"
assert_contains "dirty worktree error" "$OUTPUT" "uncommitted_changes"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Read-only sandbox ==="
# ══════════════════════════════════════════════════════════════

# Provider that mutates a file — should not affect real repo
MUTATE_PROFILE=$(mktemp)
cat > "$MUTATE_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mutator"
[providers.mutator]
type = "cli"
command = "echo 'mutated' >> tracked.txt && printf '### Summary\nModified.\n\n### Verdict\nPASS\n'"
timeout_sec = 10
healthcheck = "true"
TOML
P=$(setup_project)
echo "original" > "$P/tracked.txt"
git -C "$P" add -A && git -C "$P" commit -q -m "add tracked"
write_state "$P" 0
CCT_PROVIDER_PROFILE="$MUTATE_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
CONTENT=$(cat "$P/tracked.txt")
assert_eq "sandbox isolation: real file unchanged" "original" "$CONTENT"
rm -f "$MUTATE_PROFILE"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Plan phase advisory ==="
# ══════════════════════════════════════════════════════════════

P=$(setup_project)
write_state "$P" 0 "plan"
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" 2>&1) || RC=$?
assert_exit "plan phase FAIL exits 0 (advisory)" 0 "$RC"

if [[ -f "$P/specs/test-feat/collaboration/plan-consult.md" ]]; then
    echo "  PASS: plan-consult.md created on FAIL"
    PASS=$((PASS + 1))
else
    echo "  FAIL: plan-consult.md not created on plan FAIL"
    FAIL=$((FAIL + 1))
fi

if [[ -f "$P/.cct/review/loop-summary.json" ]]; then
    PLAN_VERDICT=$(jq -r '.verdict' "$P/.cct/review/loop-summary.json")
    assert_eq "plan loop-summary records FAIL" "FAIL" "$PLAN_VERDICT"
else
    echo "  FAIL: loop-summary.json not created for plan phase"
    FAIL=$((FAIL + 1))
fi
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Stop hook validation ==="
# ══════════════════════════════════════════════════════════════

run_hook() {
    local hook="$1" input="$2"
    shift 2
    local rc=0
    printf '%s' "$input" | env "$@" bash "$HOOKS_DIR/$hook" >/dev/null 2>/dev/null || rc=$?
    echo "$rc"
}

# PASS summary → allowed
H=$(mktemp -d)
mkdir -p "$H/.cct/review"
echo '{"phase":"build"}' > "$H/.cct/review/state.json"
echo '{"verdict":"PASS","bypass":false}' > "$H/.cct/review/loop-summary.json"
RC=$(run_hook peer-review-on-stop.sh '{"stop_hook_active":false}' CCT_PEER_REVIEW_ENABLED=true CLAUDE_PROJECT_DIR="$H")
assert_exit "stop hook: PASS → allowed" 0 "$RC"
rm -rf "$H"

# No summary, build state → blocked
H=$(mktemp -d)
mkdir -p "$H/.cct/review"
echo '{"phase":"build"}' > "$H/.cct/review/state.json"
RC=$(run_hook peer-review-on-stop.sh '{"stop_hook_active":false}' CCT_PEER_REVIEW_ENABLED=true CLAUDE_PROJECT_DIR="$H")
assert_exit "stop hook: no summary → blocked" 2 "$RC"
rm -rf "$H"

# No state at all → warning, allowed
H=$(mktemp -d)
RC=$(run_hook peer-review-on-stop.sh '{"stop_hook_active":false}' CCT_PEER_REVIEW_ENABLED=true CLAUDE_PROJECT_DIR="$H")
assert_exit "stop hook: no state → allowed" 0 "$RC"
rm -rf "$H"

# Plan phase → exempt
H=$(mktemp -d)
mkdir -p "$H/.cct/review"
echo '{"phase":"plan"}' > "$H/.cct/review/state.json"
RC=$(run_hook peer-review-on-stop.sh '{"stop_hook_active":false}' CCT_PEER_REVIEW_ENABLED=true CLAUDE_PROJECT_DIR="$H")
assert_exit "stop hook: plan → exempt" 0 "$RC"
rm -rf "$H"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Monotonic round numbering ==="
# ══════════════════════════════════════════════════════════════

P=$(setup_project)
write_state "$P" 0
# Run 3 rounds
for i in 1 2 3; do
    CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
done

ROUND_AFTER_3=$(jq -r '.current_round' "$P/.cct/review/state.json")
assert_eq "round is 3 after 3 rounds" "3" "$ROUND_AFTER_3"

# Simulate retry: increment attempt, keep round number
jq '.attempt = 2 | .loop_start = (now | floor)' "$P/.cct/review/state.json" > "$P/.cct/review/state.tmp" \
    && mv "$P/.cct/review/state.tmp" "$P/.cct/review/state.json"

# Next round should be 4, not 1
CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
ROUND_AFTER_RETRY=$(jq -r '.current_round' "$P/.cct/review/state.json")
assert_eq "round is 4 after retry (monotonic)" "4" "$ROUND_AFTER_RETRY"

if [[ -f "$P/.cct/review/findings-round-4.json" ]]; then
    echo "  PASS: findings-round-4.json exists (not overwritten)"
    PASS=$((PASS + 1))
else
    echo "  FAIL: findings-round-4.json not created"
    FAIL=$((FAIL + 1))
fi
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Collaboration artifact on PASS ==="
# ══════════════════════════════════════════════════════════════

P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$PASS_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?

ARTIFACT="$P/specs/test-feat/collaboration/build-review.md"
if [[ -f "$ARTIFACT" ]]; then
    echo "  PASS: build-review.md created"
    PASS=$((PASS + 1))
    ARTIFACT_CONTENT=$(cat "$ARTIFACT")
    assert_contains "artifact has verdict PASS" "$ARTIFACT_CONTENT" "verdict: PASS"
    assert_contains "artifact has mode review" "$ARTIFACT_CONTENT" "mode: review"
    assert_contains "artifact has rounds_completed" "$ARTIFACT_CONTENT" "rounds_completed:"
else
    echo "  FAIL: build-review.md not created"
    FAIL=$((FAIL + 1))
fi
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

echo "========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "$TEST_REVIEW_LOOP_EXPECTED_PASS" ]]; then
    echo "  FAIL: assertion-count drift (expected $TEST_REVIEW_LOOP_EXPECTED_PASS, got $PASS)"
    FAIL=$((FAIL + 1))
fi

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0
