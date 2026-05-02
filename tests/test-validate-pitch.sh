#!/usr/bin/env bash

# test-validate-pitch.sh — Tests for scripts/validate-pitch.sh
#
# Covers the happy path plus each failure mode the validator enforces:
#   1. Happy path — fully populated pitch.md passes
#   2. Missing required field (appetite) — fails
#   3. Invalid appetite enum — fails
#   4. Invalid bet_status enum — fails
#   5. Missing circuit_breaker when bet_status >= shaped — fails
#   6. Missing cycle when bet_status in {bet, building, shipped} — fails
#   7. pitch_id frontmatter mismatch with directory name — fails
#   8. Empty specs/pitches/ — exits 0 with "No pitch directories found"
#
# Run from the repo root:
#   bash tests/test-validate-pitch.sh

set -u

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VALIDATOR="$REPO_DIR/scripts/validate-pitch.sh"

PASS=0
FAIL=0

# Isolated temp area — copy validator into a fake repo with fake specs/pitches/.
TEST_TMPDIR=$(mktemp -d)
trap 'rm -rf "$TEST_TMPDIR"' EXIT

assert_ok() {
  local name="$1" result="$2"
  if [[ "$result" -eq 0 ]]; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name (rc=$result)"
    FAIL=$((FAIL + 1))
  fi
}

assert_fail() {
  local name="$1" result="$2"
  if [[ "$result" -ne 0 ]]; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name (expected non-zero, got 0)"
    FAIL=$((FAIL + 1))
  fi
}

# ── Helper: write a pitch fixture ────────────────────────────

write_pitch() {
  local dir="$1"; shift
  local pitch_id="$1"; shift
  local appetite="$1"; shift
  local bet_status="$1"; shift
  local cycle="$1"; shift
  local circuit_breaker="$1"; shift
  mkdir -p "$dir"
  cat > "$dir/pitch.md" <<EOF
---
pitch_id: $pitch_id
title: "Test pitch"
appetite: $appetite
bet_status: $bet_status
cycle: "$cycle"
circuit_breaker: "$circuit_breaker"
shaped_by: "tester"
shaped_date: 2026-05-02
---

# Pitch: Test
EOF
}

# Each test case runs the validator inside a fresh fake repo.
run_validator_in() {
  local fake_repo="$1"; shift
  ( cd "$fake_repo" && VALIDATE_PITCH_REPO="$fake_repo" bash "$VALIDATOR" "$@" )
}

echo "=== test-validate-pitch ==="
echo ""

# 1. Happy path
echo "--- 1. Happy path (valid pitch) ---"
FAKE="$TEST_TMPDIR/case-happy"
mkdir -p "$FAKE/specs/pitches"
write_pitch "$FAKE/specs/pitches/0001-foo" "0001-foo" "6w" "shaped" "" "Trim S3 if uphill at week 4."
run_validator_in "$FAKE" --all >/dev/null 2>&1
assert_ok "happy path passes" $?

# 2. Missing required field (appetite) — fails
echo "--- 2. Missing appetite ---"
FAKE="$TEST_TMPDIR/case-no-appetite"
mkdir -p "$FAKE/specs/pitches/0001-foo"
cat > "$FAKE/specs/pitches/0001-foo/pitch.md" <<'EOF'
---
pitch_id: 0001-foo
title: "x"
bet_status: shaping
cycle: ""
circuit_breaker: ""
shaped_by: "x"
shaped_date: 2026-05-02
---
EOF
run_validator_in "$FAKE" --all >/dev/null 2>&1
assert_fail "missing appetite is rejected" $?

# 3. Invalid appetite enum — fails
echo "--- 3. Invalid appetite ---"
FAKE="$TEST_TMPDIR/case-bad-appetite"
mkdir -p "$FAKE/specs/pitches"
write_pitch "$FAKE/specs/pitches/0001-foo" "0001-foo" "8w" "shaping" "" ""
run_validator_in "$FAKE" --all >/dev/null 2>&1
assert_fail "appetite=8w is rejected" $?

# 4. Invalid bet_status enum — fails
echo "--- 4. Invalid bet_status ---"
FAKE="$TEST_TMPDIR/case-bad-bet-status"
mkdir -p "$FAKE/specs/pitches"
write_pitch "$FAKE/specs/pitches/0001-foo" "0001-foo" "6w" "in-progress" "" ""
run_validator_in "$FAKE" --all >/dev/null 2>&1
assert_fail "bet_status=in-progress is rejected" $?

# 5. Missing circuit_breaker when bet_status >= shaped — fails
echo "--- 5. Missing circuit_breaker for shaped pitch ---"
FAKE="$TEST_TMPDIR/case-no-cb"
mkdir -p "$FAKE/specs/pitches"
write_pitch "$FAKE/specs/pitches/0001-foo" "0001-foo" "6w" "shaped" "" ""
run_validator_in "$FAKE" --all >/dev/null 2>&1
assert_fail "shaped pitch without circuit_breaker is rejected" $?

# Verify circuit_breaker NOT required while shaping
FAKE="$TEST_TMPDIR/case-shaping-no-cb"
mkdir -p "$FAKE/specs/pitches"
write_pitch "$FAKE/specs/pitches/0001-foo" "0001-foo" "6w" "shaping" "" ""
run_validator_in "$FAKE" --all >/dev/null 2>&1
assert_ok "shaping pitch without circuit_breaker is allowed" $?

# 6. Missing cycle when bet_status in {bet, building, shipped} — fails
echo "--- 6. Missing cycle for bet pitch ---"
FAKE="$TEST_TMPDIR/case-no-cycle-bet"
mkdir -p "$FAKE/specs/pitches"
write_pitch "$FAKE/specs/pitches/0001-foo" "0001-foo" "6w" "bet" "" "Some breaker."
run_validator_in "$FAKE" --all >/dev/null 2>&1
assert_fail "bet pitch without cycle is rejected" $?

FAKE="$TEST_TMPDIR/case-no-cycle-building"
mkdir -p "$FAKE/specs/pitches"
write_pitch "$FAKE/specs/pitches/0001-foo" "0001-foo" "6w" "building" "" "Some breaker."
run_validator_in "$FAKE" --all >/dev/null 2>&1
assert_fail "building pitch without cycle is rejected" $?

# 7. pitch_id frontmatter mismatch with directory name — fails
echo "--- 7. pitch_id mismatch ---"
FAKE="$TEST_TMPDIR/case-id-mismatch"
mkdir -p "$FAKE/specs/pitches"
write_pitch "$FAKE/specs/pitches/0001-foo" "0042-bar" "6w" "shaped" "" "Some breaker."
run_validator_in "$FAKE" --all >/dev/null 2>&1
assert_fail "pitch_id != directory name is rejected" $?

# 8. Empty specs/pitches/ — exits 0
echo "--- 8. Empty specs/pitches/ ---"
FAKE="$TEST_TMPDIR/case-empty"
mkdir -p "$FAKE/specs/pitches"
run_validator_in "$FAKE" --all >/dev/null 2>&1
assert_ok "empty specs/pitches/ exits 0" $?

# 9. No specs/pitches/ at all — exits 0
echo "--- 9. No specs/pitches/ dir ---"
FAKE="$TEST_TMPDIR/case-no-pitches-dir"
mkdir -p "$FAKE"
run_validator_in "$FAKE" --all >/dev/null 2>&1
assert_ok "no specs/pitches/ dir exits 0" $?

# 10. --pitch-id targets the canonical dogfood pitch in this repo (smoke test)
echo "--- 10. --pitch-id mode against repo's own pitch ---"
( cd "$REPO_DIR" && bash "$VALIDATOR" --pitch-id 0001-shape-up-support >/dev/null 2>&1 )
assert_ok "--pitch-id 0001-shape-up-support passes in code-copilot-team" $?

# 11. --pitch-id with non-existent id — exits 1
( cd "$REPO_DIR" && bash "$VALIDATOR" --pitch-id 9999-no-such >/dev/null 2>&1 )
assert_fail "--pitch-id 9999-no-such is rejected" $?

# 12. bash -n syntax check
echo "--- 12. Validator script syntax ---"
bash -n "$VALIDATOR"
assert_ok "validate-pitch.sh has valid bash syntax" $?

echo ""
echo "=========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "=========================================="

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
