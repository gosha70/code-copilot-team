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
echo "=== Base ref + diff cap knobs ==="
# ══════════════════════════════════════════════════════════════

# Capture profile: copies the review request to a fixed path so assertions
# can inspect the diff the reviewer actually received.
CAPTURE_FILE=$(mktemp)
CAPTURE_PROFILE=$(mktemp)
cat > "$CAPTURE_PROFILE" << TOML
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "cp {review_request} $CAPTURE_FILE && printf '### Summary\nLooks good.\n\n### Findings\n\n### Verdict\nPASS\n'"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
echo "alpha" > "$P/file-a.txt"
git -C "$P" add -A && git -C "$P" commit -q -m "commit one"
echo "beta" > "$P/file-b.txt"
git -C "$P" add -A && git -C "$P" commit -q -m "commit two"

# Default base ref (HEAD~1): only the latest commit is in the diff
write_state "$P" 0
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$CAPTURE_PROFILE" bash "$RUNNER" "$P" 2>&1) || RC=$?
assert_exit "default base ref round PASS" 0 "$RC"
assert_contains "default base ref diff has file-b" "$(cat "$CAPTURE_FILE")" "file-b.txt"
assert_eq "default base ref diff excludes file-a" "0" "$(grep -c "file-a.txt" "$CAPTURE_FILE" || true)"

# CCT_REVIEW_BASE_REF=HEAD~2: both commits are in the diff
# (drop the collaboration artifact the PASS round just wrote — it is
# untracked outside .cct/ and would trip the clean-worktree check)
rm -rf "$P/specs/test-feat/collaboration"
write_state "$P" 0
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$CAPTURE_PROFILE" CCT_REVIEW_BASE_REF="HEAD~2" bash "$RUNNER" "$P" 2>&1) || RC=$?
assert_exit "custom base ref round PASS" 0 "$RC"
assert_contains "custom base ref diff includes file-a" "$(cat "$CAPTURE_FILE")" "file-a.txt"

# CCT_REVIEW_DIFF_MAX_LINES: truncation notice honors the knob
rm -rf "$P/specs/test-feat/collaboration"
write_state "$P" 0
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$CAPTURE_PROFILE" CCT_REVIEW_BASE_REF="HEAD~2" CCT_REVIEW_DIFF_MAX_LINES=5 bash "$RUNNER" "$P" 2>&1) || RC=$?
assert_contains "diff cap truncation notice" "$(cat "$CAPTURE_FILE")" "truncated at 5 lines"
rm -rf "$P" "$CAPTURE_FILE" "$CAPTURE_PROFILE"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Collaboration validation: blocking findings ==="
# ══════════════════════════════════════════════════════════════

VALIDATOR="$SCRIPT_DIR/../scripts/validate-collaboration.sh"
P=$(mktemp -d)
mkdir -p "$P/specs/test-feat/collaboration"

# Forged artifact: hand-edited PASS with open blocking findings must fail
cat > "$P/specs/test-feat/collaboration/build-review.md" << 'MD'
---
mode: review
verdict: PASS
blocking_findings_open: 3
subject_provider: claude
peer_provider: mock
---
MD
RC=0; OUTPUT=$(bash "$VALIDATOR" --project-dir "$P" 2>&1) || RC=$?
assert_exit "forged PASS with open blocking findings fails" 1 "$RC"
assert_contains "forged PASS failure message" "$OUTPUT" "blocking findings open"

# Genuine PASS with zero open blocking findings still passes
cat > "$P/specs/test-feat/collaboration/build-review.md" << 'MD'
---
mode: review
verdict: PASS
blocking_findings_open: 0
subject_provider: claude
peer_provider: mock
---
MD
RC=0; OUTPUT=$(bash "$VALIDATOR" --project-dir "$P" 2>&1) || RC=$?
assert_exit "clean PASS still passes" 0 "$RC"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== #200: the request is not the review ==="
# ══════════════════════════════════════════════════════════════

# A provider that ECHOES ITS PROMPT before answering — exactly what
# `codex exec` does on stderr, which the runner merges via 2>&1. The echo
# carries the request's own "### Verdict / State exactly one of: PASS,
# FAIL, or INCONCLUSIVE" section and the literal FINDING| format line.
# The review itself FAILS on warning-severity grounds only, so the
# blocking-count override cannot rescue the verdict — this is the exact
# window in which the forged PASS escaped.
ECHO_PROFILE=$(mktemp)
cat > "$ECHO_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf 'user\n### Findings\nFINDING|<severity>|<category>|<file>|<line_hint>|<description>|<suggested_fix>\n\n### Verdict\nState exactly one of: PASS, FAIL, or INCONCLUSIVE\n\ncodex\n### Summary\nMaintainability only.\n\n### Findings\nFINDING|warning|design|src/api.sh|retry helper|Unbounded retry can hang|Bound the attempts\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$ECHO_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
FR="$P/.cct/review/findings-round-1.json"
assert_exit "echoed-prompt round exits FAIL, not PASS" 1 "$RC"
assert_eq "verdict comes from the LAST ### Verdict block" "FAIL" \
    "$(jq -r '.verdict' "$FR" 2>/dev/null)"
assert_eq "the echoed FINDING| template line is not a finding" "0" \
    "$(jq '[.findings[] | select(.severity | startswith("<"))] | length' "$FR" 2>/dev/null)"
assert_eq "only the real finding is recorded" "1" \
    "$(jq '.findings | length' "$FR" 2>/dev/null)"
rm -rf "$P"

# Same echo, but the provider repeats its whole answer (codex copies the
# final message to stderr too). Duplicate ids previously produced a
# multi-line first_seen_round, which crashed `jq --argjson fsr` under
# set -e and exited 2 — the code the runner documents as BREAKER_TRIPPED —
# leaving no findings file and no breaker file behind.
DUP_PROFILE=$(mktemp)
cat > "$DUP_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Findings\nFINDING|blocking|correctness|src/app.sh|near main|Missing error check|Add error handling\nFINDING|blocking|correctness|src/app.sh|near main|Missing error check|Add error handling\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$DUP_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
FR="$P/.cct/review/findings-round-1.json"
assert_exit "duplicated findings do not crash the runner (exit 1, not 2)" 1 "$RC"
assert_eq "duplicate findings are recorded once" "1" \
    "$(jq '.findings | length' "$FR" 2>/dev/null)"
assert_eq "findings file is still valid JSON" "object" \
    "$(jq -r 'type' "$FR" 2>/dev/null)"
rm -rf "$P"

# No verdict section at all: the bare-word fallback used to match "pass"
# anywhere (here, inside "password"). Fail closed instead.
NOVERDICT_PROFILE=$(mktemp)
cat > "$NOVERDICT_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Summary\nThe password handling looks fine to me.\n\n### Findings\n\n'"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$NOVERDICT_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_eq "no verdict section fails closed (INCONCLUSIVE, never PASS)" "INCONCLUSIVE" \
    "$(jq -r '.verdict' "$P/.cct/review/findings-round-1.json" 2>/dev/null)"
assert_exit "an INCONCLUSIVE round does not report success" 1 "$RC"
rm -rf "$P"

# A misspelled severity is still a real finding — the placeholder filter
# must key on the <...> shape, not an allow-list, or a review gate
# silently drops findings it does not recognise.
TYPO_PROFILE=$(mktemp)
cat > "$TYPO_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Findings\nFINDING|critical|security|src/app.sh|auth check|Auth bypass|Fix it\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
CCT_PROVIDER_PROFILE="$TYPO_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
assert_eq "an unrecognised severity is still recorded" "critical" \
    "$(jq -r '.findings[0].severity' "$P/.cct/review/findings-round-1.json" 2>/dev/null)"
rm -rf "$P"


# #200 P1: the echo can arrive AFTER the answer. stdout/stderr ordering
# under `2>&1` is not a contract, so ANY position-based rule (first block,
# last block) is unsound. The request must be unparseable, not merely
# early. Here the real review FAILS and the echoed request is appended
# last — the exact inversion that defeated the "last block wins" fix.
TAILECHO_PROFILE=$(mktemp)
cat > "$TAILECHO_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '%s\n' '### Summary' 'Maintainability only.' '' '### Findings' 'FINDING|warning|design|src/api.sh|retry helper|Unbounded retry can hang|Bound the attempts' '' '### Verdict' 'FAIL' '' 'user' '### Verdict' 'State exactly one of: PASS, FAIL, or INCONCLUSIVE'"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$TAILECHO_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "prompt echo AFTER the answer does not forge a pass" 1 "$RC"
assert_eq "trailing echoed instruction block is inert" "FAIL" \
    "$(jq -r '.verdict' "$P/.cct/review/findings-round-1.json" 2>/dev/null)"
rm -rf "$P"

# The strongest form: a provider that echoes the REAL request verbatim and
# says nothing else. If the request is unparseable by construction, this
# can only ever be INCONCLUSIVE — no ordering, no heuristics involved.
CATREQ_PROFILE=$(mktemp)
cat > "$CATREQ_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "cat {review_request}"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$CATREQ_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_eq "echoing the REAL request verbatim yields no verdict" "INCONCLUSIVE" \
    "$(jq -r '.verdict' "$P/.cct/review/findings-round-1.json" 2>/dev/null)"
assert_eq "the request's own FINDING format line is not a finding" "0" \
    "$(jq '.findings | length' "$P/.cct/review/findings-round-1.json" 2>/dev/null)"
assert_exit "verbatim-request echo fails the round" 1 "$RC"
rm -rf "$P"

# A verdict word on the heading line is prose, not a verdict.
SAMELINE_PROFILE=$(mktemp)
cat > "$SAMELINE_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '%s\n' '### Verdict: PASS, FAIL, or INCONCLUSIVE' '' 'I could not build the project.'"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
CCT_PROVIDER_PROFILE="$SAMELINE_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
assert_eq "a verdict word on the heading line is not a verdict" "INCONCLUSIVE" \
    "$(jq -r '.verdict' "$P/.cct/review/findings-round-1.json" 2>/dev/null)"
rm -rf "$P"

rm -f "$TAILECHO_PROFILE" "$CATREQ_PROFILE" "$SAMELINE_PROFILE"

# ══════════════════════════════════════════════════════════════
echo "=== #204: a broken reviewer is not a review verdict ==="
# ══════════════════════════════════════════════════════════════

# The reviewer CLI exits non-zero: it never ran. Reporting that as FAIL
# put an infrastructure failure into the content vocabulary, so the driver
# spawned fix sessions against ZERO findings and burned rounds and money.
PROVERR_PROFILE=$(mktemp)
cat > "$PROVERR_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '%s\n' 'Not inside a trusted directory and --skip-git-repo-check was not specified.' >&2; exit 1"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$PROVERR_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
FR="$P/.cct/review/findings-round-1.json"
assert_exit "a failed reviewer exits 3 (provider error), not 1 (FAIL)" 3 "$RC"
assert_eq "a failed reviewer is never a content FAIL" "INCONCLUSIVE" \
    "$(jq -r '.verdict' "$FR" 2>/dev/null)"
assert_eq "the provider error is recorded, not laundered" \
    "Not inside a trusted directory and --skip-git-repo-check was not specified." \
    "$(jq -r '.provider_error.message' "$FR" 2>/dev/null)"
assert_eq "the provider exit code is recorded" "1" \
    "$(jq -r '.provider_error.exit_code' "$FR" 2>/dev/null)"
assert_eq "no findings are invented for a review that never ran" "0" \
    "$(jq '.findings | length' "$FR" 2>/dev/null)"
rm -rf "$P"

# A timed-out reviewer is the same class: it produced no review.
PROVTO_PROFILE=$(mktemp)
cat > "$PROVTO_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "exit 124"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$PROVTO_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
FR="$P/.cct/review/findings-round-1.json"
assert_exit "a timed-out reviewer exits 3, not 1" 3 "$RC"
# The driver's provider_unavailable arm reads provider/exit/message OUT of
# this artifact, so exiting before writing it degraded the park message to
# "reviewer '?' failed (exit ?) ... unknown error".
assert_eq "a timed-out reviewer still writes the findings artifact" "1" \
    "$(ls "$P"/.cct/review/findings-round-*.json 2>/dev/null | wc -l | tr -d ' ')"
assert_eq "the timeout is named in the artifact" "timed out after 10s" \
    "$(jq -r '.provider_error.message' "$FR" 2>/dev/null)"
assert_eq "the timeout exit code is recorded" "124" \
    "$(jq -r '.provider_error.exit_code' "$FR" 2>/dev/null)"
assert_eq "a timed-out reviewer is never a content FAIL" "INCONCLUSIVE" \
    "$(jq -r '.verdict' "$FR" 2>/dev/null)"
rm -rf "$P"

# A QUIET failure: non-zero exit with no output at all. Under pipefail the
# error-extraction grep exited 1 and `set -e` aborted the runner before it
# wrote the artifact or reached exit 3 — so the driver saw rc=1 and was
# back to treating silent infrastructure failure as review feedback.
QUIET_PROFILE=$(mktemp)
cat > "$QUIET_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "exit 1"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$QUIET_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
FR="$P/.cct/review/findings-round-1.json"
assert_exit "a SILENT provider failure exits 3, not 1" 3 "$RC"
assert_eq "a silent failure still writes the findings artifact" "1" \
    "$(ls "$P"/.cct/review/findings-round-*.json 2>/dev/null | wc -l | tr -d ' ')"
assert_eq "a silent failure records 'no output', not nothing" "no output" \
    "$(jq -r '.provider_error.message' "$FR" 2>/dev/null)"
assert_eq "a silent failure is never a content FAIL" "INCONCLUSIVE" \
    "$(jq -r '.verdict' "$FR" 2>/dev/null)"
rm -rf "$P"
rm -f "$QUIET_PROFILE"

# A healthy reviewer that genuinely fails the code still exits 1.
P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "a real FAIL is still exit 1, not a provider error" 1 "$RC"
assert_eq "a real FAIL records no provider_error" "null" \
    "$(jq -r '.provider_error // "null"' "$P/.cct/review/findings-round-1.json" 2>/dev/null)"
rm -rf "$P"

rm -f "$PROVERR_PROFILE" "$PROVTO_PROFILE"

# ══════════════════════════════════════════════════════════════
echo "=== #209: a huge reviewer output must not destroy the findings file ==="
# ══════════════════════════════════════════════════════════════

# The reviewer's whole output used to travel as `--arg raw_output`, i.e. on
# argv. A verbose reviewer (codex echoes the prompt plus its reasoning, and we
# capture with 2>&1) blows past ARG_MAX; jq died with "Argument list too long"
# and, because the call sat in a heredoc command substitution, the findings
# file was written as an EMPTY 1-byte file while the console reported success.
# ~1MB of output plus real FINDING| lines, per the issue's acceptance criteria.
HUGE_REVIEWER=$(mktemp)
cat > "$HUGE_REVIEWER" << 'SH'
#!/usr/bin/env bash
# >2MB of reviewer chatter — past ARG_MAX (codex echoes the prompt and reasons at length),
# then a real review with blocking findings.
awk 'BEGIN { for (i = 0; i < 40000; i++) print "the reviewer restates the prompt and reasons at length " i }'
printf '### Findings\n'
printf 'FINDING|blocking|correctness|src/a.sh|near main|Output dirs are never cleaned|Clean them\n'
printf 'FINDING|blocking|testing|src/b.sh|golden test|OpenAPI only asserted non-null|Assert byte-identical\n'
printf 'FINDING|warning|design|src/c.sh|helper|Unbounded retry|Bound it\n'
printf '\n### Verdict\nFAIL\n'
SH
HUGE_PROFILE=$(mktemp)
cat > "$HUGE_PROFILE" << TOML
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "bash $HUGE_REVIEWER"
timeout_sec = 30
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$HUGE_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
FR="$P/.cct/review/findings-round-1.json"
assert_exit "a >ARG_MAX reviewer output still completes the round" 1 "$RC"
assert_eq "the findings file is valid JSON, not an empty stub" "object" \
    "$(jq -r 'type' "$FR" 2>/dev/null)"
assert_eq "every finding survives the large output" "3" \
    "$(jq '.findings | length' "$FR" 2>/dev/null)"
assert_eq "blocking findings are preserved" "2" \
    "$(jq '[.findings[] | select(.severity == "blocking")] | length' "$FR" 2>/dev/null)"
assert_eq "severity/file/suggested_fix survive (not just description)" "src/a.sh" \
    "$(jq -r '.findings[0].file' "$FR" 2>/dev/null)"
assert_eq "the verdict is the reviewer's, not a default" "FAIL" \
    "$(jq -r '.verdict' "$FR" 2>/dev/null)"
# raw_output is the only record of what the provider said, so it is passed by
# FILE rather than truncated — the whole transcript survives.
assert_eq "the full reviewer transcript is retained" "retained" \
    "$( [[ "$(jq -r '.raw_output | length' "$FR" 2>/dev/null || echo 0)" -gt 2000000 ]] && echo retained || echo "truncated" )"
assert_eq "no temp scratch files are left behind" "0" \
    "$(ls "$P"/.cct/review/.raw-output-* "$P"/.cct/review/.findings-round-*.tmp 2>/dev/null | wc -l | tr -d ' ')"
rm -rf "$P"
rm -f "$HUGE_PROFILE" "$HUGE_REVIEWER"
rm -f "$ECHO_PROFILE" "$DUP_PROFILE" "$NOVERDICT_PROFILE" "$TYPO_PROFILE"

# ══════════════════════════════════════════════════════════════
echo "=== #227: the max_rounds breaker must not be a dead end ==="
# ══════════════════════════════════════════════════════════════

# D1. Round numbering is monotonic, so a CUMULATIVE ceiling made
# /review-decide retry structurally impossible: with current_round=5 and
# max_rounds=5, NEXT_ROUND=6 re-tripped the breaker before the reviewer was
# ever invoked. The budget is per ATTEMPT, so retry gets a fresh one.
P=$(setup_project)
write_state "$P" 5
# Attempt 1 exhausted its budget: the breaker fires.
RC=0; CCT_REVIEW_MAX_ROUNDS=5 CCT_PROVIDER_PROFILE="$PASS_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "a spent per-attempt budget still trips the breaker" 2 "$RC"
assert_eq "the breaker reports rounds in THIS attempt" "5" \
    "$(jq -r '.rounds_this_attempt' "$P/.cct/review/breaker-tripped.json" 2>/dev/null)"

# /review-decide retry increments `attempt` and leaves current_round alone.
jq '.attempt = 2' "$P/.cct/review/state.json" > "$P/.cct/review/s.tmp" && mv "$P/.cct/review/s.tmp" "$P/.cct/review/state.json"
rm -f "$P/.cct/review/breaker-tripped.json"
RC=0; CCT_REVIEW_MAX_ROUNDS=5 CCT_PROVIDER_PROFILE="$PASS_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "after retry the next round actually RUNS" 0 "$RC"
assert_eq "round numbering stays monotonic across attempts" "6" \
    "$(jq -r '.current_round' "$P/.cct/review/state.json" 2>/dev/null)"
assert_eq "the new attempt's budget is anchored at its first round" "5" \
    "$(jq -r '.attempt_start_round' "$P/.cct/review/state.json" 2>/dev/null)"
rm -rf "$P"

# D3. A reviewer that REWORDS the same defect produced a fresh finding id
# every round, so consecutive_fixed never incremented and the stale breaker
# never fired — the loop read N "new" findings instead of one stuck
# reviewer. Staleness is now bucketed by (file, category).
REWORD1=$(mktemp); REWORD2=$(mktemp)
cat > "$REWORD1" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Findings\nFINDING|blocking|correctness|src/app.sh|near main|Output dirs are never cleaned between runs|Clean them\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML
cat > "$REWORD2" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Findings\nFINDING|blocking|correctness|src/app.sh|near main|Persistent output directories accumulate across invocations|Purge them\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
CCT_PROVIDER_PROFILE="$REWORD1" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
R1_ID=$(jq -r '.findings[0].id' "$P/.cct/review/findings-round-1.json")
R1_KEY=$(jq -r --arg id "$R1_ID" '.findings[$id].repeat_key' "$P/.cct/review/state.json")
# The fixer claims it fixed the finding; the reviewer restates it, reworded.
jq -n --argjson r 1 --arg id "$R1_ID" \
    '{round: $r, resolutions: [{finding_id: $id, disposition: "fixed", rationale: "m", commit_ref: "x"}]}' \
    > "$P/.cct/review/resolution-round-1.json"
CCT_PROVIDER_PROFILE="$REWORD2" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
R2_ID=$(jq -r '.findings[0].id' "$P/.cct/review/findings-round-2.json")
R2_KEY=$(jq -r --arg id "$R2_ID" '.findings[$id].repeat_key' "$P/.cct/review/state.json")

assert_eq "rewording still changes the finding id (unchanged behaviour)" "different" \
    "$( [[ "$R1_ID" != "$R2_ID" ]] && echo different || echo "same:$R1_ID" )"
assert_eq "but the repeat key is stable across rewording" "$R1_KEY" "$R2_KEY"
assert_eq "the reworded repeat counts as consecutive_fixed" "1" \
    "$(jq -r --arg k "$R2_KEY" '.repeats[$k].consecutive_fixed' "$P/.cct/review/state.json" 2>/dev/null)"

# Keep rewording. The default threshold is 2 CONSECUTIVE recurrences, and
# the breaker is evaluated BEFORE a round runs, so it fires on the round
# after the count reaches the threshold. Each cycle: claim fixed, restate it
# in different words.
jq -n --argjson r 2 --arg id "$R2_ID" \
    '{round: $r, resolutions: [{finding_id: $id, disposition: "fixed", rationale: "m", commit_ref: "x"}]}' \
    > "$P/.cct/review/resolution-round-2.json"
CCT_PROVIDER_PROFILE="$REWORD1" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
assert_eq "a second reworded recurrence reaches the threshold" "2" \
    "$(jq -r --arg k "$R2_KEY" '.repeats[$k].consecutive_fixed' "$P/.cct/review/state.json" 2>/dev/null)"
R3_ID=$(jq -r '.findings[0].id' "$P/.cct/review/findings-round-3.json")
jq -n --argjson r 3 --arg id "$R3_ID" \
    '{round: $r, resolutions: [{finding_id: $id, disposition: "fixed", rationale: "m", commit_ref: "x"}]}' \
    > "$P/.cct/review/resolution-round-3.json"
RC=0; CCT_PROVIDER_PROFILE="$REWORD2" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "a reworded-but-recurring defect trips the stale breaker" 2 "$RC"
assert_eq "the stale breaker names the recurrence" "stale_findings" \
    "$(jq -r '.breaker' "$P/.cct/review/breaker-tripped.json" 2>/dev/null)"
assert_eq "the stale detail explains the rewording" "1" \
    "$(jq -r '.stale_findings[0].description' "$P/.cct/review/breaker-tripped.json" 2>/dev/null | grep -c 'reworded' || true)"
rm -rf "$P"; rm -f "$REWORD1" "$REWORD2"

# ══════════════════════════════════════════════════════════════
echo "=== Two findings sharing a repeat key advance staleness once per round ==="
# ══════════════════════════════════════════════════════════════
# Two findings in the same file+category+line_hint used to
# increment the bucket twice per round (once per finding in the
# per-finding loop), so after one fixed→re-raised cycle
# consecutive_fixed jumped to 2 and tripped the threshold-2
# breaker.  Now each bucket advances once per round.
TWO_SAME=$(mktemp)
cat > "$TWO_SAME" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Findings\nFINDING|blocking|correctness|src/app.sh|near main|First defect|Fix it\nFINDING|blocking|correctness|src/app.sh|near main|Second defect in same location|Fix it too\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML
TWO_SAME_R2=$(mktemp)
cat > "$TWO_SAME_R2" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Findings\nFINDING|blocking|correctness|src/app.sh|near main|First reworded|Repair\nFINDING|blocking|correctness|src/app.sh|near main|Second reworded|Repair too\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
CCT_PROVIDER_PROFILE="$TWO_SAME" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
R1_ID1=$(jq -r '.findings[0].id' "$P/.cct/review/findings-round-1.json")
R1_ID2=$(jq -r '.findings[1].id' "$P/.cct/review/findings-round-1.json")
R1_KEY1=$(jq -r --arg id "$R1_ID1" '.findings[$id].repeat_key' "$P/.cct/review/state.json")
R1_KEY2=$(jq -r --arg id "$R1_ID2" '.findings[$id].repeat_key' "$P/.cct/review/state.json")
assert_eq "two findings in the same bucket share a repeat key" "$R1_KEY1" "$R1_KEY2"

# Mark BOTH as fixed — they share a bucket so both resolutions were "fixed"
jq -n --argjson r 1 --arg id1 "$R1_ID1" --arg id2 "$R1_ID2" \
    '{round: $r, resolutions: [{finding_id: $id1, disposition: "fixed", rationale: "m", commit_ref: "x"}, {finding_id: $id2, disposition: "fixed", rationale: "m", commit_ref: "x"}]}' \
    > "$P/.cct/review/resolution-round-1.json"
CCT_PROVIDER_PROFILE="$TWO_SAME_R2" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
assert_eq "bucket advances once per round (not per finding)" "1" \
    "$(jq -r --arg k "$R1_KEY1" '.repeats[$k].consecutive_fixed' "$P/.cct/review/state.json" 2>/dev/null)"
rm -rf "$P"; rm -f "$TWO_SAME" "$TWO_SAME_R2"

# ══════════════════════════════════════════════════════════════
echo "=== Distinct line_hints in the same file+category produce distinct repeat keys ==="
# ══════════════════════════════════════════════════════════════
# Without a location discriminator, two different correctness
# defects in the same file share a bucket and one fix can advance
# the other's staleness.  line_hint disambiguates them.
DISTINCT=$(mktemp)
cat > "$DISTINCT" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Findings\nFINDING|blocking|correctness|src/app.sh|near retry helper|Unbounded retry|Bound it\nFINDING|blocking|correctness|src/app.sh|in main loop|Dangling temp files|Clean them\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
CCT_PROVIDER_PROFILE="$DISTINCT" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
ID1=$(jq -r '.findings[0].id' "$P/.cct/review/findings-round-1.json")
ID2=$(jq -r '.findings[1].id' "$P/.cct/review/findings-round-1.json")
KEY1=$(jq -r --arg id "$ID1" '.findings[$id].repeat_key' "$P/.cct/review/state.json")
KEY2=$(jq -r --arg id "$ID2" '.findings[$id].repeat_key' "$P/.cct/review/state.json")

assert_eq "distinct line_hints produce distinct repeat keys" "different" \
    "$([[ "$KEY1" != "$KEY2" ]] && echo different || echo "same:$KEY1")"
rm -rf "$P"; rm -f "$DISTINCT"

# ══════════════════════════════════════════════════════════════
echo "=== A mixed-disposition bucket does not advance staleness ==="
# ══════════════════════════════════════════════════════════════
# One fixed sibling used to mark the whole bucket fixed, so the
# rejected sibling's natural reappearance advanced the counter as
# though a fix had failed.  A bucket is only "previously fixed"
# when EVERY finding in it was resolved as fixed.
MIXED=$(mktemp)
cat > "$MIXED" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Findings\nFINDING|blocking|correctness|src/app.sh|near main|Defect alpha|Fix alpha\nFINDING|blocking|correctness|src/app.sh|near main|Defect beta|Fix beta\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML
MIXED_R2=$(mktemp)
cat > "$MIXED_R2" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Findings\nFINDING|blocking|correctness|src/app.sh|near main|Alpha reworded|Repair\nFINDING|blocking|correctness|src/app.sh|near main|Beta reworded|Repair too\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML

P=$(setup_project)
write_state "$P" 0
CCT_PROVIDER_PROFILE="$MIXED" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
R1_ID1=$(jq -r '.findings[0].id' "$P/.cct/review/findings-round-1.json")
R1_ID2=$(jq -r '.findings[1].id' "$P/.cct/review/findings-round-1.json")
R1_KEY=$(jq -r --arg id "$R1_ID1" '.findings[$id].repeat_key' "$P/.cct/review/state.json")

# Fix alpha; reject beta — not all findings in the bucket were fixed.
jq -n --argjson r 1 --arg id1 "$R1_ID1" --arg id2 "$R1_ID2" \
    '{round: $r, resolutions: [{finding_id: $id1, disposition: "fixed", rationale: "m", commit_ref: "x"}, {finding_id: $id2, disposition: "rejected", rationale: "out of scope", commit_ref: null}]}' \
    > "$P/.cct/review/resolution-round-1.json"
CCT_PROVIDER_PROFILE="$MIXED_R2" bash "$RUNNER" "$P" >/dev/null 2>&1 || true
assert_eq "a mixed-disposition bucket does not advance staleness" "0" \
    "$(jq -r --arg k "$R1_KEY" '.repeats[$k].consecutive_fixed' "$P/.cct/review/state.json" 2>/dev/null)"
rm -rf "$P"; rm -f "$MIXED" "$MIXED_R2"

# ══════════════════════════════════════════════════════════════
echo "=== #229: runner exit codes and state integrity ==="
# Verify a normal review round stays within its content/provider contract.
# Code 4 is reserved for runner failures and is exercised below with fault
# injection. State must remain valid JSON after every path.
P=$(mktemp -d)
mkdir -p "$P/.cct/review"

# Verify a normal round exits within contract (0-3, not 5 or other)
write_state "$P" 0
rc=0
CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || rc=$?
if [[ "$rc" -ge 0 && "$rc" -le 3 ]]; then
    echo "  PASS: runner exit $rc is in documented contract (0-3)"
    PASS=$((PASS + 1))
else
    echo "  FAIL: runner exited $rc outside documented contract (0-3)"
    FAIL=$((FAIL + 1))
fi
# State must be valid JSON after run
jq empty "$P/.cct/review/state.json" >/dev/null 2>&1
assert_exit "state.json is valid JSON after round" 0 $?
# current_round must have advanced
ROUND=$(jq -r '.current_round' "$P/.cct/review/state.json")
assert_eq "state round updated to 1" "1" "$ROUND"
# findings-round-1.json must exist
assert_eq "findings-round-1.json exists" "1" "$([[ -f "$P/.cct/review/findings-round-1.json" ]] && echo 1 || echo 0)"
rm -rf "$P"

# A dispositions-form resolution is the driver's durable format. The runner
# must accept its `id` field just as it accepts `resolutions[].finding_id`.
P=$(setup_project)
write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
FINDING_ID=$(jq -r '.findings[0].id' "$P/.cct/review/findings-round-1.json")
jq -n --arg id "$FINDING_ID" \
    '{round: 1, dispositions: [{id: $id, disposition: "fixed", rationale: "fixed", commit_ref: "abc"}]}' \
    > "$P/.cct/review/resolution-round-1.json"
RC=0; CCT_PROVIDER_PROFILE="$FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "a dispositions-only resolution completes the next round" 1 "$RC"
assert_eq "a dispositions id advances the matching finding once" "1" \
    "$(jq -r --arg id "$FINDING_ID" '.findings[$id].consecutive_fixed' "$P/.cct/review/state.json")"
rm -rf "$P"

# /review-decide retry increments attempt without erasing audit history. Old
# attempt-local stale counters must not trip before the new reviewer runs.
P=$(setup_project)
write_state "$P" 3
jq '
    .attempt = 2 |
    .last_attempt = 1 |
    .attempt_start_round = 0 |
    .findings = {"old-finding": {
      description: "old defect", repeat_key: "old-bucket",
      first_seen_round: 1, rounds_seen: [1, 2, 3], consecutive_fixed: 2
    }} |
    .repeats = {"old-bucket": {
      file: "src/app.sh", category: "correctness",
      rounds_seen: [1, 2, 3], consecutive_fixed: 2
    }}
' "$P/.cct/review/state.json" > "$P/.cct/review/state.tmp"
mv "$P/.cct/review/state.tmp" "$P/.cct/review/state.json"
RC=0; CCT_PROVIDER_PROFILE="$PASS_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "retry bypasses stale counters from the prior attempt" 0 "$RC"
assert_eq "retry still advances the monotonic round" "4" \
    "$(jq -r '.current_round' "$P/.cct/review/state.json")"
assert_eq "retry anchors the new attempt at the prior round" "3" \
    "$(jq -r '.attempt_start_round' "$P/.cct/review/state.json")"
assert_eq "retry persists the new attempt identity" "2" \
    "$(jq -r '.last_attempt' "$P/.cct/review/state.json")"
assert_eq "retry clears per-finding stale state" "0" \
    "$(jq -r '.findings["old-finding"].consecutive_fixed' "$P/.cct/review/state.json")"
assert_eq "retry clears repeat-bucket stale state" "0" \
    "$(jq -r '.repeats["old-bucket"].consecutive_fixed' "$P/.cct/review/state.json")"
rm -rf "$P"

# Force only the final state builder to fail. The runner must publish neither
# a partial state nor PASS and must classify its own failure as code 4.
REAL_JQ=$(command -v jq)
JQ_SHIM_DIR=$(mktemp -d)
cat > "$JQ_SHIM_DIR/jq" << SH
#!/usr/bin/env bash
if [[ " \$* " == *" --argjson repeats "* ]]; then
    exit 5
fi
exec "$REAL_JQ" "\$@"
SH
chmod +x "$JQ_SHIM_DIR/jq"
P=$(setup_project)
write_state "$P" 0
RC=0; PATH="$JQ_SHIM_DIR:$PATH" CCT_PROVIDER_PROFILE="$PASS_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "a final state-generation failure is RUNNER_ERROR" 4 "$RC"
assert_eq "a state-generation failure preserves valid prior state" "0" \
    "$(jq -r '.current_round' "$P/.cct/review/state.json")"
assert_eq "a state-generation failure publishes no PASS summary" "0" \
    "$([[ -f "$P/.cct/review/loop-summary.json" ]] && echo 1 || echo 0)"
assert_eq "a state-generation failure removes its temp file" "0" \
    "$(find "$P/.cct/review" -name 'state.json.tmp.*' | wc -l | tr -d ' ')"
rm -rf "$P" "$JQ_SHIM_DIR"

# ══════════════════════════════════════════════════════════════
echo "=== a read-only directory in the project must not decide the verdict ==="
# ══════════════════════════════════════════════════════════════

# The snapshot copies the whole project — including any read-only entry
# (a stale worktree registration, a read-only vendor dir). Under set -e
# an unguarded cleanup rm aborted the runner with exit 1 BEFORE any
# review round: a PASS became indistinguishable from a FAIL. Cleanup now
# restores write permission and never decides the verdict.
P=$(setup_project)
write_state "$P" 0
mkdir -p "$P/readonly-vendor" && touch "$P/readonly-vendor/lib.txt"
git -C "$P" add readonly-vendor && git -C "$P" commit -q -m "vendor dir"
chmod 555 "$P/readonly-vendor"
mkdir -p "$P/.git/worktrees/stalewt" && touch "$P/.git/worktrees/stalewt/gitdir"
chmod 555 "$P/.git/worktrees/stalewt"
RC=0; CCT_PROVIDER_PROFILE="$PASS_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
chmod -R 755 "$P/.git/worktrees" "$P/readonly-vendor" 2>/dev/null
assert_exit "a PASS survives read-only directories in the project" 0 "$RC"
assert_eq "the PASS summary was published" "PASS" \
    "$(jq -r '.verdict' "$P/.cct/review/loop-summary.json" 2>/dev/null)"
rm -rf "$P"

# ══════════════════════════════════════════════════════════════
echo "=== the snapshot carries sources, never what .gitignore excludes ==="
# ══════════════════════════════════════════════════════════════

# The first real unattended run (#190, 2026-09-09) spent 73 of its 90
# minutes copying a 42 GB gitignored benchmark-runs folder into the
# review snapshot. The snapshot is what git knows about: ignored trees
# and .git are absent, tracked sources are present. The tree is clean —
# the runner refuses any uncommitted change (untracked files included)
# before any snapshot, and that refusal is its own contract.
P=$(setup_project)
write_state "$P" 0
mkdir -p "$P/runs/attempt-01" "$P/node_modules/pkg" "$P/src"
printf 'runs/\nnode_modules/\n' >> "$P/.gitignore"
echo "huge" > "$P/runs/attempt-01/worktree.bin"
echo "dep" > "$P/node_modules/pkg/index.js"
echo "tracked" > "$P/src/tracked.txt"
git -C "$P" add .gitignore src/tracked.txt && git -C "$P" commit -q -m "sources + ignores"
SNAP_SPY_DIR=$(mktemp -d)
# A reviewer that reports what it can see inside the snapshot (its cwd),
# then answers PASS in the runner's verdict format.
cat > "$SNAP_SPY_DIR/spy.sh" << SH
#!/usr/bin/env bash
ls -d runs node_modules .git src/tracked.txt 2>/dev/null > "$SNAP_SPY_DIR/seen.txt"
printf '### Summary\nLooks good.\n\n### Findings\n\n### Verdict\nPASS\n'
SH
chmod +x "$SNAP_SPY_DIR/spy.sh"
cat > "$SNAP_SPY_DIR/providers.toml" << TOML
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "$SNAP_SPY_DIR/spy.sh"
timeout_sec = 60
healthcheck = "true"
TOML
RC=0; CCT_PROVIDER_PROFILE="$SNAP_SPY_DIR/providers.toml" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "the review ran to a PASS on the trimmed snapshot" 0 "$RC"
assert_eq "the snapshot holds the tracked sources, never the ignored trees or .git" \
    "src/tracked.txt" "$(tr '\n' ' ' < "$SNAP_SPY_DIR/seen.txt" 2>/dev/null | sed 's/ $//')"
rm -rf "$P" "$SNAP_SPY_DIR"

# Snapshot SETUP failure is infrastructure (RUNNER_ERROR 4), never a
# verdict: a failed mktemp exited 1 under raw set -e, indistinguishable
# from FAIL. Injected via a mktemp PATH shim (TMPDIR is no vector — BSD
# mktemp ignores it without -t); the shim fails only -d, so the guard
# site is the first casualty.
P=$(setup_project)
write_state "$P" 0
MKTEMP_SHIM_DIR=$(mktemp -d)
cat > "$MKTEMP_SHIM_DIR/mktemp" << 'SH'
#!/usr/bin/env bash
for a in "$@"; do
    [[ "$a" == "-d" ]] && exit 1
done
exec /usr/bin/mktemp "$@"
SH
chmod +x "$MKTEMP_SHIM_DIR/mktemp"
SNAP_LOG="$MKTEMP_SHIM_DIR/runner-out.log"
RC=0; PATH="$MKTEMP_SHIM_DIR:$PATH" CCT_PROVIDER_PROFILE="$PASS_PROFILE" \
    bash "$RUNNER" "$P" > "$SNAP_LOG" 2>&1 || RC=$?
assert_exit "a failed snapshot setup is RUNNER_ERROR, not a verdict" 4 "$RC"
assert_eq "the setup failure names the snapshot" "1" \
    "$(grep -c 'could not create the snapshot directory' "$SNAP_LOG" | tr -d ' ')"
rm -rf "$P" "$MKTEMP_SHIM_DIR"

# ══════════════════════════════════════════════════════════════
echo "=== openai-compatible adapter: a reasoning model must answer, not think (#190 run 3) ==="
# ══════════════════════════════════════════════════════════════

# Run 3 reached the reviewer and lost the round to content: null — the
# Qwen model on vLLM spent the whole budget in its hidden reasoning.
# A fake OpenAI-compatible server: without chat_template_kwargs it
# answers like that server did; with the field it answers; a second
# fake rejects the field with a 400 once, so the adapter's retry
# without it is exercised.
ADP="$SCRIPT_DIR/../scripts/provider-adapters/openai-compatible.sh"
FAKE_DIR=$(mktemp -d)
cat > "$FAKE_DIR/fake.py" << 'PY'
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
MODE = sys.argv[1]; PORT = int(sys.argv[2]); LOG = sys.argv[3]
class H(BaseHTTPRequestHandler):
    seen = 0
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"up")
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        H.seen += 1
        with open(LOG, "a") as f: f.write(json.dumps(body) + "\n")
        off = body.get("chat_template_kwargs", {}).get("enable_thinking") is False
        ds_off = body.get("thinking", {}).get("type") == "disabled"
        if MODE == "rejects" and off:
            self.send_response(400); self.end_headers()
            self.wfile.write(b'{"error":{"message":"Unexpected field: chat_template_kwargs"}}'); return
        if MODE == "rejects-enable" and off:
            self.send_response(400); self.end_headers()
            self.wfile.write(b'{"error":{"message":"unexpected field: enable_thinking"}}'); return
        if MODE == "rejects-thinking" and "thinking" in body:
            self.send_response(400); self.end_headers()
            self.wfile.write(b'{"error":{"message":"Unrecognized request argument supplied: thinking"}}'); return
        if MODE == "deepseek" and not ds_off:
            msg = {"role": "assistant", "content": None, "reasoning_content": "Let me think " * 20}
            fin = "length"
        elif MODE == "thinks" and not off:
            msg = {"role": "assistant", "content": None, "reasoning": "Let me think " * 20}
            fin = "length"
        else:
            msg = {"role": "assistant", "content": "ok"}; fin = "stop"
        out = {"choices": [{"index": 0, "message": msg, "finish_reason": fin}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        if MODE == "priced":
            out["usage"] = {"prompt_tokens": 20000, "completion_tokens": 8000, "total_tokens": 28000}
        if MODE == "nousage":
            del out["usage"]
        if MODE == "badusage":
            out["usage"] = {"prompt_tokens": "many", "completion_tokens": 8000}
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(out).encode())
HTTPServer(("127.0.0.1", PORT), H).serve_forever()
PY
printf 'Reply with exactly: ok\n' > "$FAKE_DIR/req.md"
fake_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'; }
# Started detached from the suite's shell (set -e, job control) and
# awaited on the port, not on a sleep.
fake_start() {  # fake_start <mode> <port> <log>
    nohup python3 "$FAKE_DIR/fake.py" "$1" "$2" "$3" > "$FAKE_DIR/fake-$1.err" 2>&1 &
    FPID=$!
    local i
    for i in $(seq 1 50); do
        curl -s -m 1 -o /dev/null "http://127.0.0.1:$2/" 2>/dev/null && return 0
        sleep 0.1
    done
    echo "  FAIL: fake server ($1) did not come up: $(cat "$FAKE_DIR/fake-$1.err" 2>/dev/null)"; FAIL=$((FAIL + 1))
}
FP=$(fake_port); fake_start thinks "$FP" "$FAKE_DIR/thinks.log"
RC=0; OUT=$(bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --max-tokens 32 2>&1) || RC=$?
assert_exit "a content-less reasoning reply is a failure" 1 "$RC"
assert_contains "…that names the cause and the setting" "$OUT" "spent its 32-token budget on hidden reasoning"
assert_contains "…and the fix" "$OUT" "disable_thinking = true"
RC=0; OUT=$(bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --max-tokens 32 --no-thinking 2>&1) || RC=$?
assert_exit "--no-thinking gets the answer" 0 "$RC"
assert_eq "…the answer itself" "ok" "$OUT"
assert_eq "…by sending enable_thinking=false" "1" "$(grep -c '"enable_thinking": false' "$FAKE_DIR/thinks.log" | tr -d ' ')"
assert_eq "…and DeepSeek's thinking.type=disabled in the same request" "1" "$(grep -c '"thinking": {"type": "disabled"}' "$FAKE_DIR/thinks.log" | tr -d ' ')"
kill "$FPID" 2>/dev/null; wait "$FPID" 2>/dev/null || true
# A DeepSeek-style server reads thinking.type, not chat_template_kwargs
# (the D1 review lost DeepSeek to 122k characters of reasoning at 32768).
FP=$(fake_port); fake_start deepseek "$FP" "$FAKE_DIR/deepseek.log"
RC=0; OUT=$(bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --max-tokens 32 2>&1) || RC=$?
assert_exit "a DeepSeek-style reasoning-only reply is a failure" 1 "$RC"
assert_contains "…that names both switches" "$OUT" "thinking.type=disabled"
RC=0; OUT=$(bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --max-tokens 32 --no-thinking 2>&1) || RC=$?
assert_exit "--no-thinking turns a DeepSeek-style server's thinking off too" 0 "$RC"
assert_eq "…the answer itself" "ok" "$OUT"
kill "$FPID" 2>/dev/null; wait "$FPID" 2>/dev/null || true
# An OpenAI-style server that rejects the DeepSeek field is asked again
# without it, keeping the vLLM field.
FP=$(fake_port); fake_start rejects-thinking "$FP" "$FAKE_DIR/rejects-thinking.log"
RC=0; OUT=$(bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --max-tokens 32 --no-thinking 2>&1) || RC=$?
assert_exit "a server that rejects thinking.type is asked again without it" 0 "$RC"
assert_eq "…two requests, the second without the DeepSeek field" "0" "$(tail -n 1 "$FAKE_DIR/rejects-thinking.log" | grep -c '"thinking": {' | tr -d ' ')"
assert_eq "…and the second still carries the vLLM field" "1" "$(tail -n 1 "$FAKE_DIR/rejects-thinking.log" | grep -c '"enable_thinking": false' | tr -d ' ')"
kill "$FPID" 2>/dev/null; wait "$FPID" 2>/dev/null || true
FP=$(fake_port); fake_start rejects "$FP" "$FAKE_DIR/rejects.log"
RC=0; OUT=$(bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --max-tokens 32 --no-thinking 2>&1) || RC=$?
assert_exit "a server that rejects the field is asked again without it" 0 "$RC"
assert_eq "…two requests, the second without the field" "2" "$(wc -l < "$FAKE_DIR/rejects.log" | tr -d ' ')"
assert_eq "…and the second has no chat_template_kwargs" "0" "$(tail -n 1 "$FAKE_DIR/rejects.log" | grep -c chat_template_kwargs | tr -d ' ')"
assert_eq "…but keeps the DeepSeek field" "1" "$(tail -n 1 "$FAKE_DIR/rejects.log" | grep -c '"thinking": {"type": "disabled"}' | tr -d ' ')"
kill "$FPID" 2>/dev/null; wait "$FPID" 2>/dev/null || true
# A body that names "enable_thinking" names the vLLM field, not DeepSeek's.
FP=$(fake_port); fake_start rejects-enable "$FP" "$FAKE_DIR/rejects-enable.log"
RC=0; OUT=$(bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --max-tokens 32 --no-thinking 2>&1) || RC=$?
assert_exit "a 400 naming enable_thinking drops the vLLM field only" 0 "$RC"
assert_eq "…the retry has no chat_template_kwargs" "0" "$(tail -n 1 "$FAKE_DIR/rejects-enable.log" | grep -c chat_template_kwargs | tr -d ' ')"
assert_eq "…and still carries thinking.type=disabled" "1" "$(tail -n 1 "$FAKE_DIR/rejects-enable.log" | grep -c '"thinking": {"type": "disabled"}' | tr -d ' ')"
kill "$FPID" 2>/dev/null; wait "$FPID" 2>/dev/null || true

# ── Provider pricing: measured tokens at configured rates (2026-09-10) ──
# The second real unattended run's DeepSeek round was debited at the
# flat $2 estimate for a bill under a cent. With rates configured the
# adapter prices the response's usage into the #193 cost channel — a
# conservative calculated cost at peak cache-miss rates — and writes
# it BEFORE judging the answer, so a reasoning-only reply still
# records its tokens. No usable usage → nothing written → estimate.
COST_FILE="$FAKE_DIR/cost.json"
FP=$(fake_port); fake_start priced "$FP" "$FAKE_DIR/priced.log"
rm -f "$COST_FILE"
RC=0; OUT=$(CCT_REVIEW_COST_FILE="$COST_FILE" bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --price-input 0.30 --price-output 1.20 2>&1) || RC=$?
assert_exit "priced: the answer still comes back" 0 "$RC"
assert_eq "priced: 20000 in at \$0.30 + 8000 out at \$1.20 per million = \$0.0156" "0.0156" \
    "$(jq -r '.total_cost_usd' "$COST_FILE" 2>/dev/null)"
assert_eq "priced: the tokens are recorded beside the figure" "20000 8000" \
    "$(jq -r '"\(.prompt_tokens) \(.completion_tokens)"' "$COST_FILE" 2>/dev/null)"
assert_contains "priced: the basis says conservative calculated, not the bill" \
    "$(jq -r '.basis' "$COST_FILE" 2>/dev/null)" "conservative calculated cost"
rm -f "$COST_FILE"
RC=0; OUT=$(bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --price-input 0.30 --price-output 1.20 2>&1) || RC=$?
assert_eq "priced: no cost channel in the environment → nothing written" "0" "$([[ -f "$COST_FILE" ]] && echo 1 || echo 0)"
rm -f "$COST_FILE"
RC=0; OUT=$(CCT_REVIEW_COST_FILE="$COST_FILE" bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" 2>&1) || RC=$?
assert_eq "unpriced: no rates → nothing written (unmetered, the estimate applies)" "0" "$([[ -f "$COST_FILE" ]] && echo 1 || echo 0)"
RC=0; OUT=$(bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --price-input 0.30 2>&1) || RC=$?
assert_exit "one rate without the other is refused" 1 "$RC"
assert_contains "…and the refusal says so" "$OUT" "must be given together"
RC=0; OUT=$(bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --price-input 0.30 --price-output -1 2>&1) || RC=$?
assert_exit "a negative rate is refused" 1 "$RC"
kill "$FPID" 2>/dev/null; wait "$FPID" 2>/dev/null || true
# The reasoning-only failure: the cost file lands before the rejection.
FP=$(fake_port); fake_start thinks "$FP" "$FAKE_DIR/thinks2.log"
rm -f "$COST_FILE"
RC=0; OUT=$(CCT_REVIEW_COST_FILE="$COST_FILE" bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --max-tokens 32 --price-input 0.30 --price-output 1.20 2>&1) || RC=$?
assert_exit "priced reasoning-only reply is still a failure" 1 "$RC"
assert_eq "…but its tokens were priced before the rejection" "1" "$([[ -f "$COST_FILE" ]] && echo 1 || echo 0)"
assert_eq "…at the configured rates (1 in + 1 out)" "0.0000015" "$(jq -r '.total_cost_usd' "$COST_FILE" 2>/dev/null)"
kill "$FPID" 2>/dev/null; wait "$FPID" 2>/dev/null || true
# Missing or malformed usage keeps the estimate fallback, never zero.
for mode in nousage badusage; do
    FP=$(fake_port); fake_start "$mode" "$FP" "$FAKE_DIR/$mode.log"
    rm -f "$COST_FILE"
    RC=0; OUT=$(CCT_REVIEW_COST_FILE="$COST_FILE" bash "$ADP" --base-url "http://127.0.0.1:$FP/v1" --model m --input "$FAKE_DIR/req.md" --price-input 0.30 --price-output 1.20 2>&1) || RC=$?
    assert_exit "$mode: the answer still comes back" 0 "$RC"
    assert_eq "$mode: no usable usage → nothing written, not \$0" "0" "$([[ -f "$COST_FILE" ]] && echo 1 || echo 0)"
    kill "$FPID" 2>/dev/null; wait "$FPID" 2>/dev/null || true
done
# The runner hands the profile's rates to the adapter, so a probe (and a
# round) through a priced provider comes back MEASURED; an unpriced one
# stays unmetered (null).
FP=$(fake_port); fake_start priced "$FP" "$FAKE_DIR/priced2.log"
PRICED_PROFILE=$(mktemp)
cat > "$PRICED_PROFILE" << TOML
[defaults]
peer_for.claude = "priced"
[providers.priced]
type = "openai-compatible"
base_url = "http://127.0.0.1:$FP/v1"
model = "m"
price_usd_per_mtok_input = 0.30
price_usd_per_mtok_output = 1.20
healthcheck = "true"
[providers.unpriced]
type = "openai-compatible"
base_url = "http://127.0.0.1:$FP/v1"
model = "m"
healthcheck = "true"
TOML
PP2=$(mktemp -d); git -C "$PP2" init -q
PROBE_OUT=$(mktemp)
RC=0; CCT_PROVIDER_PROFILE="$PRICED_PROFILE" bash "$RUNNER" "$PP2" --probe --peer priced --out "$PROBE_OUT" >/dev/null 2>&1 || RC=$?
assert_eq "the runner hands the profile's rates to the adapter: the probe is measured" "0.0156" \
    "$(jq -r '.invocation_cost_usd' "$PROBE_OUT" 2>/dev/null)"
RC=0; CCT_PROVIDER_PROFILE="$PRICED_PROFILE" bash "$RUNNER" "$PP2" --probe --peer unpriced --out "$PROBE_OUT" >/dev/null 2>&1 || RC=$?
assert_eq "an unpriced provider stays unmetered (null)" "null" \
    "$(jq -r '.invocation_cost_usd' "$PROBE_OUT" 2>/dev/null)"
kill "$FPID" 2>/dev/null; wait "$FPID" 2>/dev/null || true
rm -rf "$PP2" "$PRICED_PROFILE" "$FAKE_DIR"

# ══════════════════════════════════════════════════════════════
echo "=== auto-build-reviewer-probe: --probe is the real path, minus the state ==="
# ══════════════════════════════════════════════════════════════
# Runs 1 and 3 of 2026-09-09 passed their healthcheck and then lost the
# first round to a reviewer that could not answer. The probe sends one
# small request through the same resolution, adapter, sandbox and
# parser and requires a parseable verdict.

PROBE_PROFILE=$(mktemp)
cat > "$PROBE_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
fallback_chain.claude = ["down", "mock"]
[providers.mock]
type = "cli"
command = "printf '### Summary\nLooks good.\n\n### Findings\n\n### Verdict\nPASS\n'"
timeout_sec = 10
healthcheck = "true"
[providers.fail]
type = "cli"
command = "printf '### Summary\nNo.\n\n### Findings\nFINDING|blocking|correctness|README.md|top|Wrong|Fix\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
[providers.echo]
type = "cli"
command = "cat {review_request}"
timeout_sec = 10
healthcheck = "true"
[providers.prose]
type = "cli"
command = "printf 'I cannot review this right now.\n'"
timeout_sec = 10
healthcheck = "true"
[providers.down]
type = "cli"
command = "true"
timeout_sec = 10
healthcheck = "false"
[providers.slow]
type = "cli"
command = "exit 124"
timeout_sec = 7
healthcheck = "true"
TOML
NOCHAIN_PROFILE=$(mktemp)
cat > "$NOCHAIN_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "down"
[providers.down]
type = "cli"
command = "true"
timeout_sec = 10
healthcheck = "false"
TOML

probe() {  # probe <profile> <peer> → RC, PROBE_OUT
    PROBE_OUT=$(mktemp)
    RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$1" bash "$RUNNER" "$PP" --probe --peer "$2" --subject claude --out "$PROBE_OUT" 2>&1) || RC=$?
}
PP=$(mktemp -d); git -C "$PP" init -q   # no .cct/review at all

probe "$PROBE_PROFILE" mock
assert_exit "probe: a reviewer that answers in format exits 0" 0 "$RC"
assert_eq "probe: the verdict is recorded as written" "PASS" "$(jq -r '.verdict' "$PROBE_OUT")"
assert_eq "probe: parseable" "true" "$(jq -r '.parseable' "$PROBE_OUT")"
assert_eq "probe: the answering provider is named" "mock" "$(jq -r '.provider' "$PROBE_OUT")"
assert_eq "probe: the requested provider is kept" "mock" "$(jq -r '.requested_provider' "$PROBE_OUT")"
assert_eq "probe: an unmetered CLI has a null cost" "null" "$(jq -r '.invocation_cost_usd' "$PROBE_OUT")"
assert_eq "probe: the fingerprint is the round's shape" "64" "$(jq -r '.fingerprint' "$PROBE_OUT" | tr -d '\n' | wc -c | tr -d ' ')"
assert_eq "probe: it leaves no review state behind" "0" "$([[ -e "$PP/.cct" ]] && echo 1 || echo 0)"

probe "$PROBE_PROFILE" fail
assert_exit "probe: a FAIL verdict is still a parseable answer (exit 0)" 0 "$RC"
assert_eq "probe: FAIL recorded as written" "FAIL" "$(jq -r '.verdict' "$PROBE_OUT")"

probe "$PROBE_PROFILE" echo
assert_exit "probe: a reviewer that echoes the request has no verdict (exit 3)" 3 "$RC"
assert_eq "probe: echoed request → not parseable" "false" "$(jq -r '.parseable' "$PROBE_OUT")"
assert_contains "probe: the error says no verdict was parseable" "$(jq -r '.error' "$PROBE_OUT")" "no parseable verdict"

probe "$PROBE_PROFILE" prose
assert_exit "probe: prose without a verdict exits 3" 3 "$RC"
assert_eq "probe: the answer's tail is kept for the triage" "I cannot review this right now." \
    "$(jq -r '.output_tail' "$PROBE_OUT" | tr -d '\n')"

probe "$PROBE_PROFILE" down
assert_exit "probe: a down primary with a healthy fallback answers (exit 0)" 0 "$RC"
assert_eq "probe: the fallback that answered is named" "mock" "$(jq -r '.provider' "$PROBE_OUT")"
assert_eq "probe: the requested primary is still recorded" "down" "$(jq -r '.requested_provider' "$PROBE_OUT")"

probe "$PROBE_PROFILE" slow
assert_exit "probe: a timed-out reviewer exits 3" 3 "$RC"
assert_eq "probe: the timeout is named" "timed out after 7s" "$(jq -r '.error' "$PROBE_OUT")"
assert_eq "probe: the timeout exit code is recorded" "124" "$(jq -r '.exit_code' "$PROBE_OUT")"

probe "$NOCHAIN_PROFILE" down
assert_exit "probe: nothing healthy in the chain exits 2" 2 "$RC"
assert_eq "probe: no provider recorded" "null" "$(jq -r '.provider' "$PROBE_OUT")"
assert_contains "probe: the error names the chain" "$(jq -r '.error' "$PROBE_OUT")" "passed its healthcheck"

RC=0; bash "$RUNNER" "$PP" --probe --out "$PROBE_OUT" >/dev/null 2>&1 || RC=$?
assert_exit "probe: --peer is required" 1 "$RC"
RC=0; bash "$RUNNER" "$PP" --bogus >/dev/null 2>&1 || RC=$?
assert_exit "an unknown runner argument is refused" 1 "$RC"
# The round's request still carries the same output-format text the
# probe sends — one function, so the two cannot drift apart.
assert_eq "one output-format text for rounds and probes" "1" \
    "$(grep -c '^required_output_format()' "$RUNNER" | tr -d ' ')"
rm -rf "$PP" "$PROBE_PROFILE" "$NOCHAIN_PROFILE"

# ══════════════════════════════════════════════════════════════
echo "=== #190 D1: a round whose provider produced no review falls back once ==="
# ══════════════════════════════════════════════════════════════
# Three of five real runs ended with a provider that passed its
# healthcheck and produced no review on the real request, while a
# healthy fallback was configured and never asked. The same request now
# goes once to the next healthy provider in the chain; a verdict from
# the first provider is final; the failed provider is never its own
# fallback; both invocations are recorded.

D1_MARK=$(mktemp -u)
D1_PROFILE=$(mktemp)
cat > "$D1_PROFILE" << TOML
[defaults]
peer_for.claude = "mock"
fallback_chain.claude = ["mock", "spare"]
[providers.mock]
type = "cli"
command = "printf 'Error: the model returned no content: hidden reasoning\n' >&2; exit 1"
timeout_sec = 10
healthcheck = "true"
[providers.spare]
type = "cli"
command = "touch $D1_MARK && printf '### Summary\nSpare looked.\n\n### Findings\n\n### Verdict\nPASS\n'"
timeout_sec = 10
healthcheck = "true"
TOML
P=$(setup_project); write_state "$P" 0
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$D1_PROFILE" bash "$RUNNER" "$P" 2>&1) || RC=$?
FR="$P/.cct/review/findings-round-1.json"
assert_exit "D1: primary produced no review, the fallback answered → the round passes (exit 0)" 0 "$RC"
assert_eq "D1: the findings name the provider that answered" "spare" "$(jq -r '.reviewer_provider' "$FR")"
assert_eq "D1: …and the one that failed" "mock" "$(jq -r '.fallback.from' "$FR")"
assert_contains "D1: …with its error kept" "$(jq -r '.fallback.error' "$FR")" "hidden reasoning"
assert_eq "D1: the failed invocation is unmetered (null), not free" "null" "$(jq -r '.fallback.invocation_cost_usd' "$FR")"
assert_eq "D1: the verdict is the fallback's" "PASS" "$(jq -r '.verdict' "$FR")"
assert_eq "D1: no provider_error on a round the fallback completed" "0" "$(jq -r 'has("provider_error") | if . then 1 else 0 end' "$FR")"
assert_eq "D1: the round counts both invocations" "2" "$(jq -r '.cost.invocations' "$P/.cct/review/state.json")"
assert_eq "D1: …both unmetered" "2" "$(jq -r '.cost.unmetered_invocations' "$P/.cct/review/state.json")"
assert_contains "D1: the console says who failed and who was tried" "$OUTPUT" "Skipping 'mock' (the provider that just failed)"
assert_contains "D1: …and that the round ran again via the fallback" "$OUTPUT" "again via fallback 'spare'"
assert_eq "D1: the collaboration artifact names the answering provider" "spare" \
    "$(grep -m1 '^peer_provider:' "$P/specs/test-feat/collaboration/build-review.md" | awk '{print $2}')"
rm -rf "$P" "$D1_MARK"

# A verdict from the first provider is final: FAIL never consults the chain.
D1_FAIL_PROFILE=$(mktemp)
cat > "$D1_FAIL_PROFILE" << TOML
[defaults]
peer_for.claude = "mock"
fallback_chain.claude = ["spare"]
[providers.mock]
type = "cli"
command = "printf '### Summary\nIssues.\n\n### Findings\nFINDING|blocking|correctness|src/app.sh|near main|Missing check|Add check\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
[providers.spare]
type = "cli"
command = "touch $D1_MARK && printf '### Summary\nSpare.\n\n### Findings\n\n### Verdict\nPASS\n'"
timeout_sec = 10
healthcheck = "true"
TOML
P=$(setup_project); write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$D1_FAIL_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "D1: a FAIL verdict is final (exit 1)" 1 "$RC"
assert_eq "D1: …the fallback was never invoked" "0" "$([[ -f "$D1_MARK" ]] && echo 1 || echo 0)"
assert_eq "D1: …and the findings carry no fallback" "0" "$(jq -r 'has("fallback") | if . then 1 else 0 end' "$P/.cct/review/findings-round-1.json")"
rm -rf "$P" "$D1_MARK"

# Both fail: the round ends as before (exit 3) and the detail names both.
D1_BOTH_PROFILE=$(mktemp)
cat > "$D1_BOTH_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
fallback_chain.claude = ["spare"]
[providers.mock]
type = "cli"
command = "printf 'Error: primary is broken\n' >&2; exit 1"
timeout_sec = 10
healthcheck = "true"
[providers.spare]
type = "cli"
command = "exit 124"
timeout_sec = 7
healthcheck = "true"
TOML
P=$(setup_project); write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$D1_BOTH_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
FR="$P/.cct/review/findings-round-1.json"
assert_exit "D1: primary and fallback both fail → provider failure (exit 3)" 3 "$RC"
assert_eq "D1: the failing provider on record is the fallback" "spare" "$(jq -r '.reviewer_provider' "$FR")"
assert_eq "D1: …its error names the primary's failure too" "timed out after 7s (after 'mock' failed first: Error: primary is broken)" \
    "$(jq -r '.provider_error.message' "$FR")"
assert_eq "D1: …and the verdict stays INCONCLUSIVE" "INCONCLUSIVE" "$(jq -r '.verdict' "$FR")"
rm -rf "$P"

# The suffix is produced for any fallback failure, not only a timeout.
D1_BOTH2_PROFILE=$(mktemp)
cat > "$D1_BOTH2_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
fallback_chain.claude = ["spare"]
[providers.mock]
type = "cli"
command = "printf 'Error: primary is broken\n' >&2; exit 1"
timeout_sec = 10
healthcheck = "true"
[providers.spare]
type = "cli"
command = "printf 'Error: spare is broken too\n' >&2; exit 1"
timeout_sec = 10
healthcheck = "true"
TOML
P=$(setup_project); write_state "$P" 0
RC=0; CCT_PROVIDER_PROFILE="$D1_BOTH2_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "D1: a fallback that fails with a plain error is a provider failure (exit 3)" 3 "$RC"
assert_eq "D1: …and the suffix names the primary's failure" \
    "Error: spare is broken too (after 'mock' failed first: Error: primary is broken)" \
    "$(jq -r '.provider_error.message' "$P/.cct/review/findings-round-1.json")"
rm -rf "$P" "$D1_BOTH2_PROFILE"

# Advisory lenses and plan consults gate nothing and never fall back
# (review of PR #339): the driver debits them as one invocation and
# files their findings under the configured provider.
P=$(setup_project); write_state "$P" 0
RC=0; CCT_REVIEW_ADVISORY=true CCT_PROVIDER_PROFILE="$D1_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_exit "D1: an advisory run does not fall back (exit 3)" 3 "$RC"
assert_eq "D1: …the fallback was never invoked for a lens" "0" "$([[ -f "$D1_MARK" ]] && echo 1 || echo 0)"
assert_eq "D1: …the findings stay under the configured provider" "mock" "$(jq -r '.reviewer_provider' "$P/.cct/review/findings-round-1.json")"
assert_eq "D1: …with no fallback recorded" "0" "$(jq -r 'has("fallback") | if . then 1 else 0 end' "$P/.cct/review/findings-round-1.json")"
rm -rf "$P" "$D1_MARK"
P=$(setup_project); write_state "$P" 0 plan
RC=0; CCT_PROVIDER_PROFILE="$D1_PROFILE" bash "$RUNNER" "$P" >/dev/null 2>&1 || RC=$?
assert_eq "D1: a plan-phase consult does not fall back either" "0" "$([[ -f "$D1_MARK" ]] && echo 1 || echo 0)"
rm -rf "$P" "$D1_MARK"

# A fallback whose healthcheck fails is skipped; with nothing healthy the
# round ends as before, with no fallback recorded.
D1_DOWN_PROFILE=$(mktemp)
cat > "$D1_DOWN_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
fallback_chain.claude = ["spare"]
[providers.mock]
type = "cli"
command = "exit 1"
timeout_sec = 10
healthcheck = "true"
[providers.spare]
type = "cli"
command = "true"
timeout_sec = 10
healthcheck = "false"
TOML
P=$(setup_project); write_state "$P" 0
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$D1_DOWN_PROFILE" bash "$RUNNER" "$P" 2>&1) || RC=$?
assert_exit "D1: an unhealthy fallback is not tried (exit 3)" 3 "$RC"
assert_eq "D1: …no fallback recorded" "0" "$(jq -r 'has("fallback") | if . then 1 else 0 end' "$P/.cct/review/findings-round-1.json")"
assert_contains "D1: …and the console says so" "$OUTPUT" "No healthy fallback for 'mock'"
rm -rf "$P" "$D1_PROFILE" "$D1_FAIL_PROFILE" "$D1_BOTH_PROFILE" "$D1_DOWN_PROFILE"

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
