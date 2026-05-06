#!/usr/bin/env bash
# test-origin-alignment.sh — exercise scripts/check-origin-alignment.sh
# across all six exit codes against isolated fixture spec trees.
#
# Uses CCT_SPECS_DIR env var to point the script at a temp dir.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO_DIR/scripts/check-origin-alignment.sh"

if [[ ! -x "$SCRIPT" ]]; then
  echo "FAIL: $SCRIPT not executable"
  exit 1
fi

TOTAL_PASS=0
TOTAL_FAIL=0

pass() { echo "  [PASS] $1"; TOTAL_PASS=$((TOTAL_PASS + 1)); }
fail() { echo "  [FAIL] $1"; TOTAL_FAIL=$((TOTAL_FAIL + 1)); }

# Run the script against a fixture, assert the expected exit code.
expect_exit() {
  local fixture="$1" expected="$2" label="$3"
  CCT_SPECS_DIR="$FIXTURE_ROOT" bash "$SCRIPT" "$fixture" >/dev/null 2>&1
  local got=$?
  if [[ "$got" -eq "$expected" ]]; then
    pass "$label (expected $expected, got $got)"
  else
    fail "$label (expected $expected, got $got)"
  fi
}

# Build a plan.md with given frontmatter content.
write_plan() {
  local dir="$1" frontmatter="$2"
  mkdir -p "$dir"
  {
    echo "---"
    printf '%s\n' "$frontmatter"
    echo "---"
    echo ""
    echo "# Plan body"
  } > "$dir/plan.md"
}

# Build an alignment record with the given verdict and confidence.
write_alignment() {
  local dir="$1" verdict="$2" confidence="$3" stamp="${4:-2030-01-01-1200}"
  cat > "$dir/origin-alignment-$stamp.md" <<EOF
# Origin alignment check

Verdict: $verdict
Confidence: $confidence
EOF
}

# Set up isolated fixture root.
FIXTURE_ROOT="$(mktemp -d -t origin-align-tests.XXXXXX)"
trap 'rm -rf "$FIXTURE_ROOT"' EXIT

echo "=== Origin alignment script: exit codes ==="
echo "FIXTURE_ROOT=$FIXTURE_ROOT"

# ── Exit 0: aligned, high ────────────────────────────────────
DIR="$FIXTURE_ROOT/fix-aligned-high"
write_plan "$DIR" "feature_id: fix-aligned-high
spec_mode: lightweight
status: draft
origin:
  issue: gosha70/code-copilot-team#1
  origin_claim: |
    User said: build it."
write_alignment "$DIR" "aligned" "high"
expect_exit "fix-aligned-high" 0 "aligned, high → exit 0"

# ── Exit 1: aligned, medium ──────────────────────────────────
DIR="$FIXTURE_ROOT/fix-aligned-medium"
write_plan "$DIR" "feature_id: fix-aligned-medium
spec_mode: lightweight
status: draft
origin:
  issue: gosha70/code-copilot-team#2
  origin_claim: |
    User said: build it."
write_alignment "$DIR" "aligned" "medium"
expect_exit "fix-aligned-medium" 1 "aligned, medium → exit 1"

# ── Exit 1: aligned, low ─────────────────────────────────────
DIR="$FIXTURE_ROOT/fix-aligned-low"
write_plan "$DIR" "feature_id: fix-aligned-low
spec_mode: lightweight
status: draft
origin:
  issue: gosha70/code-copilot-team#3
  origin_claim: |
    User said: build it."
write_alignment "$DIR" "aligned" "low"
expect_exit "fix-aligned-low" 1 "aligned, low → exit 1"

# ── Exit 2: partial ──────────────────────────────────────────
DIR="$FIXTURE_ROOT/fix-partial"
write_plan "$DIR" "feature_id: fix-partial
spec_mode: lightweight
status: draft
origin:
  issue: gosha70/code-copilot-team#4
  origin_claim: |
    User said: build it."
write_alignment "$DIR" "partial" "high"
expect_exit "fix-partial" 2 "partial → exit 2"

# ── Exit 3: derailed ─────────────────────────────────────────
DIR="$FIXTURE_ROOT/fix-derailed"
write_plan "$DIR" "feature_id: fix-derailed
spec_mode: lightweight
status: draft
origin:
  issue: gosha70/code-copilot-team#5
  origin_claim: |
    User said: build it."
write_alignment "$DIR" "derailed" "high"
expect_exit "fix-derailed" 3 "derailed → exit 3"

# ── Exit 1: derailed + fresh origin-divergence.md (option C) ─
DIR="$FIXTURE_ROOT/fix-derailed-with-divergence"
write_plan "$DIR" "feature_id: fix-derailed-with-divergence
spec_mode: lightweight
status: draft
origin:
  issue: gosha70/code-copilot-team#5
  origin_claim: |
    User said: build it."
write_alignment "$DIR" "derailed" "high"
# Divergence file written AFTER the alignment record (option C committed).
sleep 1
echo "User accepted this divergence on 2026-05-06." > "$DIR/origin-divergence.md"
expect_exit "fix-derailed-with-divergence" 1 "derailed + fresh origin-divergence.md → exit 1 (option C unblock)"

# ── Exit 1: partial + fresh origin-divergence.md (option C) ──
DIR="$FIXTURE_ROOT/fix-partial-with-divergence"
write_plan "$DIR" "feature_id: fix-partial-with-divergence
spec_mode: lightweight
status: draft
origin:
  issue: gosha70/code-copilot-team#5
  origin_claim: |
    User said: build it."
write_alignment "$DIR" "partial" "high"
sleep 1
echo "Partial scope acknowledged." > "$DIR/origin-divergence.md"
expect_exit "fix-partial-with-divergence" 1 "partial + fresh origin-divergence.md → exit 1 (option C unblock)"

# ── Exit 3: derailed + STALE origin-divergence.md (older than record) ─
DIR="$FIXTURE_ROOT/fix-derailed-stale-divergence"
write_plan "$DIR" "feature_id: fix-derailed-stale-divergence
spec_mode: lightweight
status: draft
origin:
  issue: gosha70/code-copilot-team#5
  origin_claim: |
    User said: build it."
# Divergence written FIRST, alignment record AFTER → divergence is stale.
echo "Old divergence note." > "$DIR/origin-divergence.md"
touch -t 199001010000 "$DIR/origin-divergence.md"
write_alignment "$DIR" "derailed" "high"
expect_exit "fix-derailed-stale-divergence" 3 "derailed + stale origin-divergence.md → exit 3 (no unblock)"

# ── Exit 4: no alignment record ──────────────────────────────
DIR="$FIXTURE_ROOT/fix-no-record"
write_plan "$DIR" "feature_id: fix-no-record
spec_mode: lightweight
status: draft
origin:
  issue: gosha70/code-copilot-team#6
  origin_claim: |
    User said: build it."
expect_exit "fix-no-record" 4 "no alignment record → exit 4"

# ── Exit 4: stale alignment record ───────────────────────────
DIR="$FIXTURE_ROOT/fix-stale"
write_plan "$DIR" "feature_id: fix-stale
spec_mode: lightweight
status: draft
origin:
  issue: gosha70/code-copilot-team#7
  origin_claim: |
    User said: build it."
write_alignment "$DIR" "aligned" "high" "1990-01-01-0000"
# Force the alignment record's mtime to be earlier than plan.md's.
touch -t 199001010000 "$DIR/origin-alignment-1990-01-01-0000.md"
touch "$DIR/plan.md"
expect_exit "fix-stale" 4 "stale alignment record (older than plan.md) → exit 4"

# ── Exit 5: missing origin ───────────────────────────────────
DIR="$FIXTURE_ROOT/fix-missing-origin"
write_plan "$DIR" "feature_id: fix-missing-origin
spec_mode: lightweight
status: draft"
expect_exit "fix-missing-origin" 5 "missing origin block → exit 5"

# ── Exit 0: origin: { type: internal } ───────────────────────
DIR="$FIXTURE_ROOT/fix-internal"
write_plan "$DIR" "feature_id: fix-internal
spec_mode: lightweight
status: draft
origin:
  type: internal
  reason: \"Pure framework refactor.\""
expect_exit "fix-internal" 0 "origin: { type: internal } → exit 0"

# ── Exit 5: origin: { type: internal } without reason ────────
DIR="$FIXTURE_ROOT/fix-internal-no-reason"
write_plan "$DIR" "feature_id: fix-internal-no-reason
spec_mode: lightweight
status: draft
origin:
  type: internal"
expect_exit "fix-internal-no-reason" 5 "origin: { type: internal } missing reason → exit 5"

# ── Exit 5: origin: { type: unrecoverable } ──────────────────
DIR="$FIXTURE_ROOT/fix-unrecoverable"
write_plan "$DIR" "feature_id: fix-unrecoverable
spec_mode: lightweight
status: draft
origin:
  type: unrecoverable
  note: \"Lost to time.\""
expect_exit "fix-unrecoverable" 5 "origin: { type: unrecoverable } → exit 5"

# ── Exit 5: origin block with no identifier ──────────────────
DIR="$FIXTURE_ROOT/fix-empty-origin"
write_plan "$DIR" "feature_id: fix-empty-origin
spec_mode: lightweight
status: draft
origin:
  origin_claim: |
    A claim with no source identifier."
expect_exit "fix-empty-origin" 5 "origin: with only origin_claim → exit 5"

# ── Exit 5: feature dir not found ────────────────────────────
expect_exit "nonexistent-feature-id-xyz" 5 "missing feature dir → exit 5"

# ── --help works ─────────────────────────────────────────────
CCT_SPECS_DIR="$FIXTURE_ROOT" bash "$SCRIPT" --help >/dev/null 2>&1
HELP_EXIT=$?
if [[ "$HELP_EXIT" -eq 0 ]]; then
  pass "--help → exit 0"
else
  fail "--help → exit 0 (got $HELP_EXIT)"
fi

# ── No arguments → usage + exit 5 ────────────────────────────
CCT_SPECS_DIR="$FIXTURE_ROOT" bash "$SCRIPT" >/dev/null 2>&1
NOARG_EXIT=$?
if [[ "$NOARG_EXIT" -eq 5 ]]; then
  pass "no args → exit 5"
else
  fail "no args → exit 5 (got $NOARG_EXIT)"
fi

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$TOTAL_PASS" "$TOTAL_FAIL"
echo "========================================="

if [[ $TOTAL_FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
