#!/usr/bin/env bash

# test-auto-build-loop.sh — Autonomous build driver integration tests
#
# Covers: preflight rejections, profile guard, ledger init, phase loop with
# mock claude sessions, caps, review integration (FAIL→fix→PASS, breaker),
# origin parking, milestone pause/sign-off/resume, dry-run purity, and
# resume idempotency. All providers and claude are mocked — no network.
#
# Run from the repo root:
#   bash tests/test-auto-build-loop.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DRIVER="$SCRIPT_DIR/../scripts/auto-build-loop.sh"
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

# ── Mock claude ───────────────────────────────────────────────
# Behavior per invocation is driven by env:
#   MOCK_CLAUDE_SCRIPT  — scriptlet sourced in the project dir (writes files)
#   MOCK_CLAUDE_SUBTYPE — result subtype (default success)
#   MOCK_CLAUDE_COST    — total_cost_usd per session (default 0.01)
# A counter file lets scriptlets vary behavior across sessions.

MOCK_BIN=$(mktemp -d)
cat > "$MOCK_BIN/claude" << 'MOCK'
#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then echo "mock-claude 0.0.1"; exit 0; fi
COUNTER_FILE="${MOCK_CLAUDE_COUNTER:-/tmp/mock-claude-count}"
COUNT=$(( $(cat "$COUNTER_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$COUNT" > "$COUNTER_FILE"
export MOCK_SESSION_N="$COUNT"
if [[ -n "${MOCK_CLAUDE_SCRIPT:-}" && -f "$MOCK_CLAUDE_SCRIPT" ]]; then
    # shellcheck source=/dev/null
    source "$MOCK_CLAUDE_SCRIPT"
fi
printf '{"subtype":"%s","session_id":"mock-session-%s","total_cost_usd":%s,"num_turns":3,"result":"done"}\n' \
    "${MOCK_CLAUDE_SUBTYPE:-success}" "$COUNT" "${MOCK_CLAUDE_COST:-0.01}"
MOCK
chmod +x "$MOCK_BIN/claude"

# ── Mock reviewer profiles (same shapes as test-review-loop.sh) ──

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

FAIL_ONCE_PROFILE=$(mktemp)
# Fails round 1, passes later rounds (marker file distinguishes rounds).
cat > "$FAIL_ONCE_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "if [ -f /tmp/cct-mock-reviewed ]; then printf '### Summary\nFixed.\n\n### Findings\n\n### Verdict\nPASS\n'; else touch /tmp/cct-mock-reviewed && printf '### Summary\nIssues.\n\n### Findings\nFINDING|blocking|correctness|demo.sh|near top|Missing check|Add check\n\n### Verdict\nFAIL\n'; fi"
timeout_sec = 10
healthcheck = "true"
TOML

FAIL_ALWAYS_PROFILE=$(mktemp)
cat > "$FAIL_ALWAYS_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Summary\nIssues.\n\n### Findings\nFINDING|blocking|correctness|demo.sh|near top|Missing check|Add check\n\n### Verdict\nFAIL\n'"
timeout_sec = 10
healthcheck = "true"
TOML

DOWN_PROFILE=$(mktemp)
cat > "$DOWN_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf 'unreachable'"
timeout_sec = 10
healthcheck = "false"
TOML

trap 'rm -rf "$MOCK_BIN" "$PASS_PROFILE" "$FAIL_ONCE_PROFILE" "$FAIL_ALWAYS_PROFILE" "$DOWN_PROFILE" /tmp/cct-mock-reviewed' EXIT

# ── Project factory ───────────────────────────────────────────

setup_project() {
    # setup_project [plan_status]
    local status="${1:-approved}"
    local dir
    dir=$(mktemp -d)
    git -C "$dir" init -q -b main-dev
    git -C "$dir" config user.email "test@test.local"
    git -C "$dir" config user.name "Test"
    mkdir -p "$dir/specs/demo-feat"
    cat > "$dir/specs/demo-feat/plan.md" << PLAN
---
spec_mode: lightweight
feature_id: demo-feat
status: $status
date: 2026-07-13
origin:
  type: internal
  reason: driver test fixture
  origin_claim: |
    Toy feature for auto-build driver tests.
---
# Plan: demo
PLAN
    cat > "$dir/specs/demo-feat/spec.md" << 'SPEC'
# Spec: demo

## Requirements
- FR-1: demo.sh prints ok.
- FR-2: extra.sh prints more.

## Constraints
- None.
SPEC
    cat > "$dir/specs/demo-feat/tasks.md" << 'TASKS'
# Tasks: demo

## US1: Print ok

| # | Task | File(s) |
|---|------|---------|
| 1 | Create demo.sh printing ok | demo.sh |

**Checkpoint US1**
- [ ] tests pass

## US2: Print more

| # | Task | File(s) |
|---|------|---------|
| 2 | Create extra.sh printing more | extra.sh |

**Checkpoint US2**
- [ ] tests pass
TASKS
    cat > "$dir/specs/demo-feat/automation.json" << 'CFG'
{
  "schema_version": 1,
  "profile": "advisory",
  "branch": {"name": "feature/demo-feat", "base": "main-dev"},
  "phases": {"milestone_every": 2, "max_phases": 8},
  "build": {"max_turns": 10, "max_fix_sessions_per_phase": 2},
  "test": {"command": "bash ./project-test.sh", "timeout_sec": 60},
  "review": {"reviewers": [{"provider": "mock", "specialization": "correctness", "scope": "both", "gating": true}]},
  "caps": {"wall_clock_sec": 3600, "cost_usd": 5}
}
CFG
    printf '#!/usr/bin/env bash\nexit 0\n' > "$dir/project-test.sh"
    chmod +x "$dir/project-test.sh"
    printf '.cct/\n' > "$dir/.gitignore"
    git -C "$dir" add -A
    git -C "$dir" commit -q -m "init"
    echo "$dir"
}

# run_driver <project> [driver args...] — captures OUTPUT and RC
run_driver() {
    local project="$1"; shift
    local counter
    counter=$(mktemp)
    rm -f /tmp/cct-mock-reviewed
    RC=0
    OUTPUT=$(cd "$project" && \
        CCT_PROJECT_DIR="$project" \
        CCT_CLAUDE_BIN="$MOCK_BIN/claude" \
        MOCK_CLAUDE_COUNTER="$counter" \
        CCT_PROVIDER_PROFILE="${REVIEW_PROFILE:-$PASS_PROFILE}" \
        bash "$DRIVER" demo-feat "$@" 2>&1) || RC=$?
}

# Default build scriptlet: phase 1 writes demo.sh, phase 2 writes extra.sh,
# fix sessions touch a fix marker file.
DEFAULT_SCRIPT=$(mktemp)
cat > "$DEFAULT_SCRIPT" << 'SCRIPTLET'
# A pending findings file means this is a review-fix session: write the
# resolution per the disposition contract (driver injects commit_ref after).
latest=$(ls .cct/review/findings-round-*.json 2>/dev/null | sort | tail -1)
if [[ -n "$latest" ]]; then
    round=$(basename "$latest" | sed 's/findings-round-\([0-9]*\).json/\1/')
    echo "fix pass $MOCK_SESSION_N" >> fixes.log
    jq '{round: .round, dispositions: [.findings[]? | {id: .id, disposition: "fixed", rationale: "mock fix", commit_ref: ""}]}' \
        "$latest" > ".cct/review/resolution-round-$round.json"
elif [[ ! -f demo.sh ]]; then
    printf '#!/usr/bin/env bash\necho ok\n' > demo.sh
elif [[ ! -f extra.sh ]]; then
    printf '#!/usr/bin/env bash\necho more\n' > extra.sh
else
    echo "fix pass $MOCK_SESSION_N" >> fixes.log
fi
SCRIPTLET
export MOCK_CLAUDE_SCRIPT="$DEFAULT_SCRIPT"

# ══════════════════════════════════════════════════════════════
echo "=== US1: preflight rejections ==="
# ══════════════════════════════════════════════════════════════

# Non-advisory profile rejected (FR-1)
P=$(setup_project)
run_driver "$P" --profile pr
assert_exit "profile pr rejected" 1 "$RC"
assert_contains "profile rejection names later increment" "$OUTPUT" "not available in this increment"

# Unapproved plan rejected (FR-2)
P2=$(setup_project draft)
run_driver "$P2"
assert_exit "draft plan rejected" 1 "$RC"
assert_contains "approval gate message" "$OUTPUT" "Plan Approval Gate"
rm -rf "$P2"

# Dirty worktree rejected (FR-2)
P3=$(setup_project)
echo "dirty" > "$P3/uncommitted.txt"
run_driver "$P3"
assert_exit "dirty worktree rejected" 1 "$RC"
assert_contains "dirty worktree message" "$OUTPUT" "not clean"
rm -rf "$P3"

# Unhealthy gating reviewer parks (FR-2a)
P4=$(setup_project)
REVIEW_PROFILE="$DOWN_PROFILE" run_driver "$P4"
assert_exit "unhealthy reviewer parks" 4 "$RC"
ESC_REASON=$(jq -r '.reason' "$P4"/.cct/auto-build/demo-feat/escalations/esc-1.json 2>/dev/null)
assert_eq "escalation reason provider_unavailable" "provider_unavailable" "$ESC_REASON"
rm -rf "$P4"

# Missing config rejected
P5=$(setup_project)
rm "$P5/specs/demo-feat/automation.json"
run_driver "$P5"
assert_exit "missing automation.json rejected" 1 "$RC"
rm -rf "$P5"

# FR-2a: chain semantics mirror the runner — primary healthy is enough even
# with a broken fallback; primary broken falls through to a healthy fallback.
CHAIN_PROFILE=$(mktemp)
cat > "$CHAIN_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
fallback_chain.claude = ["backup"]
[providers.mock]
type = "cli"
command = "printf 'ok'"
timeout_sec = 10
healthcheck = "true"
[providers.backup]
type = "cli"
command = "printf 'ok'"
timeout_sec = 10
healthcheck = "false"
TOML
RC=0; CCT_PROVIDER_PROFILE="$CHAIN_PROFILE" bash "$SCRIPT_DIR/../scripts/providers-health.sh" --profile "$CHAIN_PROFILE" --provider mock >/dev/null 2>&1 || RC=$?
assert_exit "primary healthy + fallback broken passes" 0 "$RC"

sed -i '' 's/healthcheck = "true"/healthcheck = "XBROKENX"/; s/healthcheck = "false"/healthcheck = "true"/; s/healthcheck = "XBROKENX"/healthcheck = "false"/' "$CHAIN_PROFILE" 2>/dev/null || \
    sed -i 's/healthcheck = "true"/healthcheck = "XBROKENX"/; s/healthcheck = "false"/healthcheck = "true"/; s/healthcheck = "XBROKENX"/healthcheck = "false"/' "$CHAIN_PROFILE"
RC=0; bash "$SCRIPT_DIR/../scripts/providers-health.sh" --profile "$CHAIN_PROFILE" --provider mock >/dev/null 2>&1 || RC=$?
assert_exit "primary broken + fallback healthy passes" 0 "$RC"

sed -i '' 's/healthcheck = "true"/healthcheck = "false"/' "$CHAIN_PROFILE" 2>/dev/null || \
    sed -i 's/healthcheck = "true"/healthcheck = "false"/' "$CHAIN_PROFILE"
RC=0; bash "$SCRIPT_DIR/../scripts/providers-health.sh" --profile "$CHAIN_PROFILE" --provider mock >/dev/null 2>&1 || RC=$?
assert_exit "whole chain broken fails" 1 "$RC"
rm -f "$CHAIN_PROFILE"

# FR-2a: an unhealthy provider UNRELATED to the gating reviewer must not block
MIXED_PROFILE=$(mktemp)
cat > "$MIXED_PROFILE" << 'TOML'
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "printf '### Summary\nLooks good.\n\n### Findings\n\n### Verdict\nPASS\n'"
timeout_sec = 10
healthcheck = "true"
[providers.broken-unrelated]
type = "cli"
command = "printf 'nope'"
timeout_sec = 10
healthcheck = "false"
TOML
P6=$(setup_project)
REVIEW_PROFILE="$MIXED_PROFILE" run_driver "$P6"
assert_exit "unrelated broken provider does not block (targeted health)" 3 "$RC"
rm -rf "$P6" "$MIXED_PROFILE"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== US1/US4: dry run has zero side effects ==="
# ══════════════════════════════════════════════════════════════

run_driver "$P" --dry-run
assert_exit "dry run exits 0" 0 "$RC"
assert_contains "dry run prints phase 1" "$OUTPUT" "phase 1: building"
assert_contains "dry run prints milestone" "$OUTPUT" "milestone-paused"
DIRTY=$(git -C "$P" status --porcelain)
assert_eq "dry run leaves worktree clean" "" "$DIRTY"
if [[ -d "$P/.cct/auto-build" ]]; then
    echo "  FAIL: dry run created ledger dir"
    FAIL=$((FAIL + 1))
else
    echo "  PASS: dry run created no ledger"
    PASS=$((PASS + 1))
fi

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== US2/US3/US4: two-phase advisory happy path ==="
# ══════════════════════════════════════════════════════════════

run_driver "$P"
assert_exit "run pauses at milestone (exit 3)" 3 "$RC"
LEDGER="$P/.cct/auto-build/demo-feat/state.json"
assert_eq "status milestone-paused" "milestone-paused" "$(jq -r '.status' "$LEDGER")"
assert_eq "phase 1 done" "done" "$(jq -r '.phases["1"].status' "$LEDGER")"
assert_eq "phase 2 done" "done" "$(jq -r '.phases["2"].status' "$LEDGER")"
BRANCH=$(git -C "$P" rev-parse --abbrev-ref HEAD)
assert_eq "on isolated feature branch" "feature/demo-feat" "$BRANCH"
COMMITS=$(git -C "$P" log --oneline | grep -c '\[auto-build\]')
assert_eq "auto-build commits present (2 feat + 2 docs)" "4" "$COMMITS"
assert_contains "phase commit message format" "$(git -C "$P" log --format=%s)" "feat(demo-feat): phase 1"
if [[ -d "$P/.cct/auto-build/demo-feat/phase-1/review" && -d "$P/.cct/auto-build/demo-feat/phase-2/review" ]]; then
    echo "  PASS: review archived per phase"
    PASS=$((PASS + 1))
else
    echo "  FAIL: review archives missing"
    FAIL=$((FAIL + 1))
fi
assert_contains "summary has milestone checkpoint" "$(cat "$P/specs/demo-feat/automation-summary.md")" "checkpoint-after-phase: 2"
EVENTS_FILE="$P/.cct/auto-build/demo-feat/events.jsonl"
assert_contains "events journal has phase_done" "$(cat "$EVENTS_FILE")" "phase_done"
REMOTE_CALLS=$(git -C "$P" log --all --oneline | wc -l)
if git -C "$P" remote | grep -q .; then
    echo "  FAIL: driver added a git remote (advisory must not push)"
    FAIL=$((FAIL + 1))
else
    echo "  PASS: no remotes touched (advisory never pushes)"
    PASS=$((PASS + 1))
fi

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== US4: milestone sign-off + resume to done ==="
# ══════════════════════════════════════════════════════════════

# Resume without sign-off refuses
run_driver "$P" --resume
assert_exit "resume without sign-off refused" 1 "$RC"
assert_contains "sign-off missing message" "$OUTPUT" "approved-by"

# Sign off, then resume completes
echo "approved-by: gosha 2026-07-13" >> "$P/specs/demo-feat/automation-summary.md"
run_driver "$P" --resume
assert_exit "resume after sign-off completes" 0 "$RC"
assert_eq "final status done" "done" "$(jq -r '.status' "$LEDGER")"
assert_contains "resume skipped done phases" "$OUTPUT" "already done"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== US3: review FAIL -> fix -> PASS with commit_ref ==="
# ══════════════════════════════════════════════════════════════

P=$(setup_project)
# Only one phase so the run completes without milestone pause.
sed -i '' 's/"milestone_every": 2/"milestone_every": 0/' "$P/specs/demo-feat/automation.json" 2>/dev/null || \
    sed -i 's/"milestone_every": 2/"milestone_every": 0/' "$P/specs/demo-feat/automation.json"
awk '/^## US2/{exit} {print}' "$P/specs/demo-feat/tasks.md" > "$P/specs/demo-feat/tasks-one.md"
mv "$P/specs/demo-feat/tasks-one.md" "$P/specs/demo-feat/tasks.md"
git -C "$P" add -A && git -C "$P" commit -q -m "single phase fixture"
REVIEW_PROFILE="$FAIL_ONCE_PROFILE" run_driver "$P"
assert_exit "FAIL->fix->PASS run completes" 0 "$RC"
FIX_COMMIT=$(git -C "$P" log --format=%s | grep -c 'fix(demo-feat): address review round')
assert_eq "fix commit created" "1" "$FIX_COMMIT"
ARCHIVE="$P/.cct/auto-build/demo-feat/phase-1/review"
RES_FILE=$(ls "$ARCHIVE"/resolution-round-*.json 2>/dev/null | head -1)
if [[ -n "$RES_FILE" ]]; then
    REFS=$(jq '[.. | objects | select(.disposition? == "fixed") | .commit_ref] | map(select(. != null and . != "")) | length' "$RES_FILE")
    if [[ "$REFS" -ge 1 ]]; then
        echo "  PASS: commit_ref injected into fixed dispositions"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: no commit_ref in fixed dispositions"
        FAIL=$((FAIL + 1))
    fi
else
    echo "  FAIL: resolution file missing from archive"
    FAIL=$((FAIL + 1))
fi
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== US3: review breaker parks ==="
# ══════════════════════════════════════════════════════════════

P=$(setup_project)
REVIEW_PROFILE="$FAIL_ALWAYS_PROFILE" run_driver "$P"
assert_exit "persistent FAIL parks (exit 4)" 4 "$RC"
LEDGER="$P/.cct/auto-build/demo-feat/state.json"
assert_eq "status parked" "parked" "$(jq -r '.status' "$LEDGER")"
ESC=$(ls "$P"/.cct/auto-build/demo-feat/escalations/esc-*.json | head -1)
assert_eq "reason review_breaker" "review_breaker" "$(jq -r '.reason' "$ESC")"
# Parked resume is refused in this increment (full resolution detection = #70)
run_driver "$P" --resume
assert_exit "parked resume refused (increment C pending)" 1 "$RC"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== US2: caps ==="
# ══════════════════════════════════════════════════════════════

# Cost cap: sessions cost more than the cap allows
P=$(setup_project)
MOCK_CLAUDE_COST=6 run_driver "$P"
assert_exit "cost cap parks" 4 "$RC"
ESC=$(ls "$P"/.cct/auto-build/demo-feat/escalations/esc-*.json | head -1)
assert_eq "reason cap_exceeded" "cap_exceeded" "$(jq -r '.reason' "$ESC")"
assert_contains "cost cap detail" "$(jq -r '.detail' "$ESC")" "cost cap"
rm -rf "$P"

# Max-phases cap
P=$(setup_project)
run_driver "$P" --max-phases 1
assert_exit "max-phases cap parks before phase 2" 4 "$RC"
ESC=$(ls "$P"/.cct/auto-build/demo-feat/escalations/esc-*.json | head -1)
assert_contains "max_phases detail" "$(jq -r '.detail' "$ESC")" "max_phases"
rm -rf "$P"

# Empty diff from build session parks as git_anomaly
P=$(setup_project)
NOOP_SCRIPT=$(mktemp)
echo ":" > "$NOOP_SCRIPT"
MOCK_CLAUDE_SCRIPT="$NOOP_SCRIPT" run_driver "$P"
assert_exit "no-op build session parks" 4 "$RC"
ESC=$(ls "$P"/.cct/auto-build/demo-feat/escalations/esc-*.json | head -1)
assert_eq "reason git_anomaly" "git_anomaly" "$(jq -r '.reason' "$ESC")"
rm -f "$NOOP_SCRIPT"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== US4: origin gate parks ==="
# ══════════════════════════════════════════════════════════════

P=$(setup_project)
# Break the origin frontmatter so check-origin-alignment fails structurally
# (exit >= 2 family; internal-type exemption removed).
sed -i '' 's/^  type: internal$/  issue: missing-repo#0/' "$P/specs/demo-feat/plan.md" 2>/dev/null || \
    sed -i 's/^  type: internal$/  issue: missing-repo#0/' "$P/specs/demo-feat/plan.md"
git -C "$P" add -A && git -C "$P" commit -q -m "break origin"
run_driver "$P"
assert_exit "origin gate parks at preflight" 4 "$RC"
ESC=$(ls "$P"/.cct/auto-build/demo-feat/escalations/esc-*.json | head -1)
assert_eq "reason origin_gate" "origin_gate" "$(jq -r '.reason' "$ESC")"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== US4: resume idempotency (kill after phase commit) ==="
# ══════════════════════════════════════════════════════════════

P=$(setup_project)
# First: run to milestone (both phases done), sign off, resume to done.
run_driver "$P"
assert_exit "setup run reaches milestone" 3 "$RC"
FEAT_COMMITS_BEFORE=$(git -C "$P" log --format=%s | grep -c '^feat(demo-feat)')
echo "approved-by: gosha 2026-07-13" >> "$P/specs/demo-feat/automation-summary.md"
run_driver "$P" --resume
assert_exit "resume completes" 0 "$RC"
FEAT_COMMITS_AFTER=$(git -C "$P" log --format=%s | grep -c '^feat(demo-feat)')
assert_eq "no duplicate phase commits on resume" "$FEAT_COMMITS_BEFORE" "$FEAT_COMMITS_AFTER"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== US4: crash after phase commit, before review ==="
# ══════════════════════════════════════════════════════════════

# Fabricate the exact mid-crash ledger state: the phase commit exists, review
# never ran. Resume MUST review the persisted phase_base_ref..HEAD diff, not
# an empty HEAD..HEAD diff.
P=$(setup_project)
sed -i '' 's/"milestone_every": 2/"milestone_every": 0/' "$P/specs/demo-feat/automation.json" 2>/dev/null || \
    sed -i 's/"milestone_every": 2/"milestone_every": 0/' "$P/specs/demo-feat/automation.json"
awk '/^## US2/{exit} {print}' "$P/specs/demo-feat/tasks.md" > "$P/specs/demo-feat/tasks-one.md"
mv "$P/specs/demo-feat/tasks-one.md" "$P/specs/demo-feat/tasks.md"
git -C "$P" add -A && git -C "$P" commit -q -m "single phase fixture"
git -C "$P" checkout -q -b feature/demo-feat
BASE_SHA=$(git -C "$P" rev-parse HEAD)
printf '#!/usr/bin/env bash\necho ok\n' > "$P/demo.sh"
git -C "$P" add -A
git -C "$P" commit -q -m "feat(demo-feat): phase 1 — US1: Print ok [auto-build]"
PHASE_SHA=$(git -C "$P" rev-parse HEAD)
mkdir -p "$P/.cct/auto-build/demo-feat"
jq -n --arg base "$BASE_SHA" --arg sha "$PHASE_SHA" --argjson started "$(date +%s)" \
    '{schema_version: 1, feature_id: "demo-feat", profile: "advisory",
      status: "in-review", current_phase: 1,
      branch: "feature/demo-feat", branch_base_ref: $base,
      phases: {"1": {title: "US1: Print ok", status: "building",
                     phase_base_ref: $base, build_commit: $sha,
                     commits: [$sha], fix_sessions: 0}},
      caps: {max_phases: 8, max_fix_sessions_per_phase: 2,
             max_wall_clock_sec: 3600, max_cost_usd: 5},
      totals: {cost_usd: 0, started_epoch: $started},
      milestones: {every_n_phases: 0, last_paused_after_phase: 0},
      escalations: [], pr: {number: null, url: null}, updated: "fabricated"}' \
    > "$P/.cct/auto-build/demo-feat/state.json"

CRASH_CAPTURE=$(mktemp)
CRASH_PROFILE=$(mktemp)
cat > "$CRASH_PROFILE" << TOML
[defaults]
peer_for.claude = "mock"
[providers.mock]
type = "cli"
command = "cp {review_request} $CRASH_CAPTURE && printf '### Summary\nLooks good.\n\n### Findings\n\n### Verdict\nPASS\n'"
timeout_sec = 10
healthcheck = "true"
TOML
REVIEW_PROFILE="$CRASH_PROFILE" run_driver "$P" --resume
assert_exit "crash-resume completes" 0 "$RC"
assert_contains "crash-resume reviewed the phase diff (demo.sh present)" "$(cat "$CRASH_CAPTURE")" "demo.sh"
FEAT_COMMITS=$(git -C "$P" log --format=%s | grep -c '^feat(demo-feat)')
assert_eq "no duplicate phase commit on crash-resume" "1" "$FEAT_COMMITS"
rm -f "$CRASH_CAPTURE" "$CRASH_PROFILE"
rm -rf "$P"

echo ""

# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

echo "========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_AUTO_BUILD_LOOP_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_AUTO_BUILD_LOOP_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL + 1))
fi

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0
