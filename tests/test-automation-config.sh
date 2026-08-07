#!/usr/bin/env bash
# test-automation-config.sh — #191 (Increment A of #190) Phase 1: the
# dedicated automation.json validator. Accept/reject matrix mirroring
# shared/schemas/automation.schema.json.
#
# Run from the repo root: bash tests/test-automation-config.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
V="$REPO_DIR/scripts/validate-automation-config.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/cct-autocfg.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0
assert() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name"; fi
}
assert_rejects() {
    local name="$1" file="$2" needle="$3"
    local out rc=0
    out="$(bash "$V" "$file" 2>&1)" || rc=$?
    if [[ $rc -eq 1 && "$out" == *"$needle"* ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (rc=$rc)"; echo "$out" | sed 's/^/    /'; fi
}
w() { printf '%s' "$2" > "$TMP/$1"; }

echo "=== automation-config validator tests ==="

# ── accepts ──
w v1.json '{"schema_version":1,"profile":"advisory"}'
assert "v1 minimal config is valid" bash "$V" "$TMP/v1.json"

w v1caps.json '{"schema_version":1,"profile":"merge","caps":{"cost_usd":25,"wall_clock_sec":14400}}'
assert "v1 with caps is valid" bash "$V" "$TMP/v1caps.json"

w v2.json '{"schema_version":2,"profile":"pr"}'
assert "v2 without an unattended block is valid" bash "$V" "$TMP/v2.json"

w v2u.json '{"schema_version":2,"profile":"unattended","caps":{"cost_usd":100,"wall_clock_sec":28800},"unattended":{"on_review_breaker":"terminate","on_stale_finding":"terminate","on_origin_gate":"terminate","budget":{"meter_all_invocations":true,"estimate_unmetered":true,"estimate_usd_per_invocation":2.0}}}'
assert "v2 unattended with explicit caps is valid" bash "$V" "$TMP/v2u.json"

assert "the shipped template is valid" bash "$V" "$REPO_DIR/shared/templates/sdd/automation-template.json"

# ── rejects ──
w r1.json '{"schema_version":1,"profile":"unattended","caps":{"cost_usd":100,"wall_clock_sec":1}}'
assert_rejects "v1 cannot request the unattended profile" "$TMP/r1.json" "requires schema_version 2"

w r2.json '{"schema_version":1,"profile":"merge","unattended":{"on_origin_gate":"terminate"}}'
assert_rejects "v1 cannot carry an unattended block" "$TMP/r2.json" "requires schema_version 2"

w r3.json '{"schema_version":2,"profile":"unattended","caps":{"wall_clock_sec":28800}}'
assert_rejects "unattended without explicit cost cap is rejected" "$TMP/r3.json" "EXPLICIT caps.cost_usd"

w r4.json '{"schema_version":2,"profile":"unattended","caps":{"cost_usd":100}}'
assert_rejects "unattended without explicit wall-clock cap is rejected" "$TMP/r4.json" "EXPLICIT caps.wall_clock_sec"

w r5.json '{"schema_version":2,"profile":"unattended","caps":{"cost_usd":100,"wall_clock_sec":1},"unattended":{"on_origin_gate":"adjudicate"}}'
assert_rejects "on_origin_gate != terminate is rejected (all increments)" "$TMP/r5.json" "ALL increments"

w r6.json '{"schema_version":2,"profile":"unattended","caps":{"cost_usd":100,"wall_clock_sec":1},"unattended":{"on_review_breaker":"adjudicate"}}'
assert_rejects "recovery values are unrequestable in increment A" "$TMP/r6.json" "increment D"

w r7.json '{"schema_version":2,"profile":"unattended","caps":{"cost_usd":100,"wall_clock_sec":1},"unattended":{"on_stale_finding":"swap_builder"}}'
assert_rejects "swap_builder is unrequestable in increment A" "$TMP/r7.json" "increment D"

w r8.json '{"schema_version":3,"profile":"advisory"}'
assert_rejects "unknown schema_version is rejected" "$TMP/r8.json" "not supported"

w r9.json '{"schema_version":2,"profile":"yolo"}'
assert_rejects "unknown profile is rejected" "$TMP/r9.json" "unknown profile"

w r10.json '{"schema_version":2,"profile":"unattended","caps":{"cost_usd":-5,"wall_clock_sec":1}}'
assert_rejects "non-positive cap is rejected" "$TMP/r10.json" "number > 0"

w r11.json '{"schema_version":2,"profile":"unattended","caps":{"cost_usd":100,"wall_clock_sec":1},"unattended":{"surprise":"key"}}'
assert_rejects "unknown unattended key is rejected (closed schema)" "$TMP/r11.json" "unknown key"

w r12.json 'not json at all'
assert_rejects "malformed JSON is rejected" "$TMP/r12.json" "not a JSON object"

w r13.json '{"schema_version":2,"profile":"unattended","caps":{"cost_usd":100,"wall_clock_sec":1},"unattended":{"budget":{"estimate_usd_per_invocation":0}}}'
assert_rejects "zero estimate is rejected" "$TMP/r13.json" "number > 0"

# ── malformed SHAPES must be violations (exit 1), never crashes (P2 review) ──
w r14.json '{"schema_version":2,"profile":"unattended","caps":{"cost_usd":100,"wall_clock_sec":1},"unattended":{"budget":"bad"}}'
assert_rejects "budget as a string is a violation" "$TMP/r14.json" "budget must be an object"

w r15.json '{"schema_version":2,"profile":"unattended","caps":{"cost_usd":100,"wall_clock_sec":1},"unattended":{"budget":{"extra":1}}}'
assert_rejects "unknown budget key is a violation (closed object)" "$TMP/r15.json" "unknown key 'unattended.budget.extra'"

w r16.json '{"schema_version":2,"profile":"merge","unattended":[]}'
assert_rejects "unattended as an array is a violation, not a crash" "$TMP/r16.json" "unattended must be an object"

w r17.json '{"schema_version":2,"profile":"merge","unattended":null}'
assert_rejects "unattended as null is a violation, not a crash" "$TMP/r17.json" "unattended must be an object"

w r18.json '{"schema_version":2,"profile":"unattended","caps":"bad","unattended":{"on_origin_gate":"terminate"}}'
assert_rejects "caps as a string is a violation, not a crash" "$TMP/r18.json" "caps must be an object"

w r19.json '{"schema_version":2,"profile":"unattended","caps":{"cost_usd":"100","wall_clock_sec":1}}'
assert_rejects "string-typed cap is a violation" "$TMP/r19.json" "number > 0"

# The schema file itself is valid JSON and pins the A-increment enums.
assert "schema file is valid JSON" jq -e . "$REPO_DIR/shared/schemas/automation.schema.json"
assert "schema pins on_* enums to terminate" \
    bash -c "jq -e '.properties.unattended.properties | [.on_review_breaker.enum, .on_stale_finding.enum, .on_origin_gate.enum] | flatten | unique == [\"terminate\"]' '$REPO_DIR/shared/schemas/automation.schema.json'"

echo ""
echo "========================================="
echo "  automation-config tests: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
