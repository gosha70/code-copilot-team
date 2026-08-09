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
