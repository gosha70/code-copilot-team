#!/usr/bin/env bash

# test-typecheck-gate.sh — T6.5: the CCT-scoped `tsc --noEmit` type-check gate.
#
# Covers (specs/pi-harness-adoption FR-016):
#   - the Pi runtime type-checks CLEAN under the committed tsconfig
#     (a green baseline — strip-types runs the runtime but never checks it)
#   - the verify-runner `type-check` gate reports supported+pass when typescript
#     is installed, and unsupported (never a fake pass) when it is not
#   - a generic project without the runtime tsconfig -> unsupported
#
# In CI, set CCT_REQUIRE_TSC=1 (after `npm install`) so the SUPPORTED path is
# actually exercised — otherwise a tsc-less host would only cover the fallback.
#
# Run from the repo root:
#   bash tests/test-typecheck-gate.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$REPO_DIR/scripts/verify-runner.sh"
TSCONFIG="$REPO_DIR/adapters/pi/runtime/tsconfig.json"
RES="$REPO_DIR/.cct/verify/result.json"

PASS=0
FAIL=0
assert() {
  local name="$1" condition="$2"
  if eval "$condition"; then echo "  PASS: $name"; PASS=$((PASS + 1))
  else echo "  FAIL: $name"; FAIL=$((FAIL + 1)); fi
}

run_gate() { CCT_VERIFY_GATES=type-check bash "$RUNNER" "$1" >/dev/null 2>&1 || true; }

echo "=== type-check gate tests (T6.5) ==="
assert "runtime tsconfig is present" "[[ -f '$TSCONFIG' ]]"

# Resolve tsc the same way the gate does (project node_modules).
TSC=""
[[ -x "$REPO_DIR/node_modules/.bin/tsc" ]] && TSC="$REPO_DIR/node_modules/.bin/tsc"

if [[ -n "$TSC" ]]; then
  echo "--- tsc present ($("$TSC" --version)) — exercising the SUPPORTED path ---"
  assert "tsc --noEmit is clean over adapters/pi/runtime (green baseline)" \
    "( cd '$REPO_DIR' && '$TSC' --noEmit -p '$TSCONFIG' )"
  run_gate "$REPO_DIR"
  assert "gate reports status supported when tsc present" "grep -q '\"status\": \"supported\"' '$RES'"
  assert "gate reports pass:true when tsc present" "grep -q '\"pass\": true' '$RES'"
  rm -r "$REPO_DIR/.cct" 2>/dev/null || true
else
  echo "--- tsc absent — exercising the UNSUPPORTED fallback ---"
  if [[ "${CCT_REQUIRE_TSC:-}" == "1" ]]; then
    echo "  FAIL: CCT_REQUIRE_TSC=1 but typescript is not installed (run npm install)"
    FAIL=$((FAIL + 1))
  fi
  run_gate "$REPO_DIR"
  assert "gate reports unsupported when tsc absent" "grep -q '\"status\": \"unsupported\"' '$RES'"
  assert "gate never fakes a pass (pass:false)" "grep -q '\"pass\": false' '$RES'"
  rm -r "$REPO_DIR/.cct" 2>/dev/null || true
fi

# Always-on: a generic project without the runtime tsconfig -> unsupported.
TMP="$(mktemp -d)"
run_gate "$TMP"
assert "no runtime tsconfig -> unsupported" "grep -q '\"status\": \"unsupported\"' '$TMP/.cct/verify/result.json'"
assert "no runtime tsconfig -> not a fake pass" "grep -q '\"pass\": false' '$TMP/.cct/verify/result.json'"
rm -r "$TMP"

echo ""
echo "========================================="
echo "  type-check gate tests: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
