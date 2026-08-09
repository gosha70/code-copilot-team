#!/usr/bin/env bash
# test-automation-config.sh — #191 (Increment A of #190) Phase 1: the
# dedicated automation.json validator. Accept/reject matrix mirroring
# shared/schemas/automation.schema.json.
#
# Run from the repo root: bash tests/test-automation-config.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
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

# Pre-#191 documents omit these keys; driver defaults apply (FR-6).
w d1.json '{}'
assert "empty config defaults to v1 advisory (pre-#191 compat)" bash "$V" "$TMP/d1.json"

w d2.json '{"profile":"merge"}'
assert "missing schema_version defaults to 1" bash "$V" "$TMP/d2.json"

w d3.json '{"schema_version":2}'
assert "missing profile defaults to advisory" bash "$V" "$TMP/d3.json"

# ── rejects ──
w r1.json '{"schema_version":1,"profile":"unattended","caps":{"cost_usd":100,"wall_clock_sec":1}}'
assert_rejects "v1 cannot request the unattended profile" "$TMP/r1.json" "requires schema_version 2"

w r1b.json '{"profile":"unattended","caps":{"cost_usd":100,"wall_clock_sec":1}}'
assert_rejects "unattended with a DEFAULTED schema_version (=1) is rejected" "$TMP/r1b.json" "requires schema_version 2"

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

# ══════════════════════════════════════════════════════════════
echo "=== #222 C1: verification.coverage ==="
# ══════════════════════════════════════════════════════════════

COV_OK='"command":"npm run coverage","artifact":"coverage/coverage-summary.json","parser":"istanbul","baseline":"none","min_line_pct":80'

# A project with NO verification block is unchanged (FR-2).
w c-none.json '{"schema_version":2,"profile":"pr"}'
assert "no verification block is still valid" bash "$V" "$TMP/c-none.json"

w c-ok.json "{\"schema_version\":2,\"profile\":\"pr\",\"verification\":{\"coverage\":{$COV_OK}}}"
assert "greenfield coverage block is valid" bash "$V" "$TMP/c-ok.json"

w c-brown.json '{"schema_version":2,"profile":"pr","verification":{"coverage":{"command":"npm run coverage","artifact":"coverage/coverage-summary.json","parser":"lcov","baseline":"admission","min_line_pct":80,"max_regression_pct":0,"timeout_sec":1200,"floor_enforced_at":"phase"}}}'
assert "brownfield coverage block is valid" bash "$V" "$TMP/c-brown.json"

# ── the four sub-blocks C1 does NOT implement are rejected BY NAME ──
for sub in test app visual conformance; do
    w "c-$sub.json" "{\"schema_version\":2,\"verification\":{\"$sub\":{}}}"
    assert_rejects "verification.$sub is rejected by name" "$TMP/c-$sub.json" "verification.$sub is not supported in C1"
done
w c-conf2.json '{"schema_version":2,"verification":{"conformance":{"required":true}}}'
assert_rejects "conformance.required names its derivation" "$TMP/c-conf2.json" "DERIVED from verification.yaml"

# ── required keys ──
for req in command artifact parser baseline; do
    w "c-miss-$req.json" "$(python3 - "$req" << 'PYEOF'
import json,sys
cov={"command":"c","artifact":"a.json","parser":"istanbul","baseline":"none","min_line_pct":80}
cov.pop(sys.argv[1])
print(json.dumps({"schema_version":2,"verification":{"coverage":cov}}))
PYEOF
)"
    assert_rejects "coverage.$req is required" "$TMP/c-miss-$req.json" "verification.coverage.$req is required"
done

# ── parsers: two implemented, two refused by name ──
for p in cobertura jacoco; do
    w "c-parser-$p.json" "{\"schema_version\":2,\"verification\":{\"coverage\":{\"command\":\"c\",\"artifact\":\"a.json\",\"parser\":\"$p\",\"baseline\":\"none\",\"min_line_pct\":80}}}"
    assert_rejects "parser $p refuses rather than pretends" "$TMP/c-parser-$p.json" "not implemented in C1"
done
w c-parser-x.json '{"schema_version":2,"verification":{"coverage":{"command":"c","artifact":"a.json","parser":"nope","baseline":"none","min_line_pct":80}}}'
assert_rejects "unknown parser is rejected" "$TMP/c-parser-x.json" "must be one of: istanbul, lcov"

# ── artifact containment (lexical here; realpath at execution) ──
w c-abs.json '{"schema_version":2,"verification":{"coverage":{"command":"c","artifact":"/etc/passwd","parser":"istanbul","baseline":"none","min_line_pct":80}}}'
assert_rejects "absolute artifact path is rejected" "$TMP/c-abs.json" "relative path inside the project"
w c-dots.json '{"schema_version":2,"verification":{"coverage":{"command":"c","artifact":"../outside/cov.json","parser":"istanbul","baseline":"none","min_line_pct":80}}}'
assert_rejects "traversing artifact path is rejected" "$TMP/c-dots.json" "must not traverse outside"

# ── floors and percentages ──
w c-nofloor.json '{"schema_version":2,"verification":{"coverage":{"command":"c","artifact":"a.json","parser":"istanbul","baseline":"none"}}}'
assert_rejects "a contract with no floor at all is rejected" "$TMP/c-nofloor.json" "needs at least one floor"
w c-range.json '{"schema_version":2,"verification":{"coverage":{"command":"c","artifact":"a.json","parser":"istanbul","baseline":"none","min_line_pct":140}}}'
assert_rejects "out-of-range percentage is rejected" "$TMP/c-range.json" "0..100"

# ── max_regression_pct is inert under greenfield, so it is refused ──
w c-regr.json '{"schema_version":2,"verification":{"coverage":{"command":"c","artifact":"a.json","parser":"istanbul","baseline":"none","min_line_pct":80,"max_regression_pct":0}}}'
assert_rejects "max_regression_pct with baseline none is rejected" "$TMP/c-regr.json" "nothing to regress from"

# ── bound must be positive ──
w c-to.json '{"schema_version":2,"verification":{"coverage":{"command":"c","artifact":"a.json","parser":"istanbul","baseline":"none","min_line_pct":80,"timeout_sec":0}}}'
assert_rejects "non-positive timeout_sec is rejected" "$TMP/c-to.json" "timeout_sec must be a number > 0"

# ── closed objects ──
w c-unk.json '{"schema_version":2,"verification":{"coverage":{"command":"c","artifact":"a.json","parser":"istanbul","baseline":"none","min_line_pct":80,"bogus":1}}}'
assert_rejects "unknown coverage key is rejected" "$TMP/c-unk.json" "unknown key 'verification.coverage.bogus'"
w c-unk2.json '{"schema_version":2,"verification":{"bogus":{}}}'
assert_rejects "unknown verification key is rejected" "$TMP/c-unk2.json" "unknown key 'verification.bogus'"

w c-at.json '{"schema_version":2,"verification":{"coverage":{"command":"c","artifact":"a.json","parser":"istanbul","baseline":"none","min_line_pct":80,"floor_enforced_at":"whenever"}}}'
assert_rejects "floor_enforced_at enum is enforced" "$TMP/c-at.json" "'landing' or 'phase'"

echo ""
echo "========================================="
echo "  automation-config tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_AUTOMATION_CONFIG_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_AUTOMATION_CONFIG_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]

