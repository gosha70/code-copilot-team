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
# The gate writes `<project>/.cct/verify/result.json`. To keep a working checkout
# SAFE, every gate invocation runs against an ISOLATED temp project (a copy of
# the runtime tree) — never the repo — so the test never touches the real `.cct`
# state (e.g. `.cct/pi-workflow.json`). A trap removes the temp root on exit.
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

TMPROOT="$(mktemp -d)"
trap 'rm -rf "$TMPROOT"' EXIT

# Snapshot whether the checkout already has runtime state, so the safety
# guardrail can tell "the test created a real .cct" (a bug) from "one was
# already there" (fine — the test structurally never writes to the checkout).
CCT_PREEXISTED=false
[[ -e "$REPO_DIR/.cct" ]] && CCT_PREEXISTED=true

PASS=0
FAIL=0
assert() {
  local name="$1" condition="$2"
  if eval "$condition"; then echo "  PASS: $name"; PASS=$((PASS + 1))
  else echo "  FAIL: $name"; FAIL=$((FAIL + 1)); fi
}

run_gate() { CCT_VERIFY_GATES=type-check bash "$RUNNER" "$1" >/dev/null 2>&1 || true; }

# An isolated project that mirrors the runtime scope, so the gate's `.cct` writes
# land in the temp tree, never the real checkout. $1 = "with-tsc" | "no-tools".
make_project() {
  local mode="$1" proj
  proj="$(mktemp -d "$TMPROOT/proj.XXXXXX")"
  mkdir -p "$proj/adapters/pi"
  cp -R "$REPO_DIR/adapters/pi/runtime" "$proj/adapters/pi/runtime"
  # tsc + @types/node resolve through the repo's node_modules (the gate also
  # falls back to it, but the project copy needs @types/node for `node:` imports).
  if [[ "$mode" == "with-tsc" ]]; then ln -s "$REPO_DIR/node_modules" "$proj/node_modules"; fi
  echo "$proj"
}

echo "=== type-check gate tests (T6.5) ==="
assert "runtime tsconfig is present" "[[ -f '$TSCONFIG' ]]"

# Resolve tsc the same way the gate does (project node_modules).
TSC=""
[[ -x "$REPO_DIR/node_modules/.bin/tsc" ]] && TSC="$REPO_DIR/node_modules/.bin/tsc"

if [[ -n "$TSC" ]]; then
  echo "--- tsc present ($("$TSC" --version)) — exercising the SUPPORTED path ---"
  # Green baseline: tsc --noEmit over the real runtime tsconfig (no `.cct` write).
  assert "tsc --noEmit is clean over adapters/pi/runtime (green baseline)" \
    "( cd '$REPO_DIR' && '$TSC' --noEmit -p '$TSCONFIG' )"
  PROJ="$(make_project with-tsc)"
  run_gate "$PROJ"
  RES="$PROJ/.cct/verify/result.json"
  assert "gate reports status supported when tsc present" "grep -q '\"status\": \"supported\"' '$RES'"
  assert "gate reports pass:true when tsc present" "grep -q '\"pass\": true' '$RES'"
else
  echo "--- tsc absent — exercising the UNSUPPORTED fallback ---"
  if [[ "${CCT_REQUIRE_TSC:-}" == "1" ]]; then
    echo "  FAIL: CCT_REQUIRE_TSC=1 but typescript is not installed (run npm install)"
    FAIL=$((FAIL + 1))
  fi
  PROJ="$(make_project no-tools)"
  run_gate "$PROJ"
  RES="$PROJ/.cct/verify/result.json"
  assert "gate reports unsupported when tsc absent" "grep -q '\"status\": \"unsupported\"' '$RES'"
  assert "gate never fakes a pass (pass:false)" "grep -q '\"pass\": false' '$RES'"
fi

# A generic project without the runtime tsconfig -> unsupported.
EMPTY="$(mktemp -d "$TMPROOT/empty.XXXXXX")"
run_gate "$EMPTY"
assert "no runtime tsconfig -> unsupported" "grep -q '\"status\": \"unsupported\"' '$EMPTY/.cct/verify/result.json'"
assert "no runtime tsconfig -> not a fake pass" "grep -q '\"pass\": false' '$EMPTY/.cct/verify/result.json'"

# Safety guardrail: the test must never CREATE a real .cct in the checkout.
if [[ "$CCT_PREEXISTED" == "false" ]]; then
  assert "test created no .cct in the real checkout" "[[ ! -e '$REPO_DIR/.cct' ]]"
else
  echo "  SKIP: .cct guardrail — a real .cct pre-existed (test never writes there)"
fi

echo ""
echo "========================================="
echo "  type-check gate tests: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
