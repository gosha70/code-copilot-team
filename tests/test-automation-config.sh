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

# ── verification.test is rejected BY NAME (top-level test.command stays
#    the single source). `app` and `visual` were rejected the same way as
#    placeholders until C3 (#239) defined them — see their sections. ──
w c-test.json '{"schema_version":2,"verification":{"test":{}}}'
assert_rejects "verification.test is rejected by name" "$TMP/c-test.json" "verification.test is not supported"
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

# ── #224 review: parity between the schema and this jq gate ──
# There is no JSON-Schema runtime here or in CI (the repo chose jq-based
# enforcement precisely so hosts need no schema tooling), so "parity"
# cannot mean "run both engines". It means two things that ARE checkable:
#   1. a fixture table where each instance's expected verdict is asserted
#      against the shell validator — the gate that actually runs;
#   2. structural assertions that the schema DECLARES the same cross-field
#      rules, so the documentation cannot silently drift from the gate.
# Stated plainly because the weaker guarantee is the honest one.
SCHEMA="$REPO_DIR/shared/schemas/automation.schema.json"

parity() {  # parity <name> <json> <expect ok|reject> [needle]
    local name="$1" json="$2" expect="$3" needle="${4:-}"
    w "parity.json" "$json"
    if [[ "$expect" == "ok" ]]; then
        assert "parity: $name" bash "$V" "$TMP/parity.json"
    else
        assert_rejects "parity: $name" "$TMP/parity.json" "$needle"
    fi
}

COVB='"command":"c","artifact":"cov.json","parser":"istanbul"'
parity "floor via min_line_pct"   "{\"verification\":{\"coverage\":{$COVB,\"baseline\":\"none\",\"min_line_pct\":80}}}" ok
parity "floor via min_branch_pct" "{\"verification\":{\"coverage\":{$COVB,\"baseline\":\"none\",\"min_branch_pct\":70}}}" ok
parity "floor via preset"         "{\"verification\":{\"coverage\":{$COVB,\"baseline\":\"none\",\"preset\":\"ml-app\"}}}" ok
parity "no floor and no preset"   "{\"verification\":{\"coverage\":{$COVB,\"baseline\":\"none\"}}}" reject "needs at least one floor"
parity "greenfield + regression"  "{\"verification\":{\"coverage\":{$COVB,\"baseline\":\"none\",\"min_line_pct\":80,\"max_regression_pct\":0}}}" reject "nothing to regress from"
parity "brownfield no threshold"  "{\"verification\":{\"coverage\":{$COVB,\"baseline\":\"admission\",\"min_line_pct\":80}}}" reject "required for baseline 'admission'"
parity "brownfield + threshold"   "{\"verification\":{\"coverage\":{$COVB,\"baseline\":\"admission\",\"min_line_pct\":80,\"max_regression_pct\":0}}}" ok
parity "brownfield + preset"      "{\"verification\":{\"coverage\":{$COVB,\"baseline\":\"admission\",\"preset\":\"ml-app\"}}}" ok

# Shape rules the schema states and the gate must actually enforce.
parity "command must be a string" "{\"verification\":{\"coverage\":{\"command\":{},\"artifact\":\"cov.json\",\"parser\":\"istanbul\",\"baseline\":\"none\",\"min_line_pct\":80}}}" reject "command must be a non-empty string"
parity "artifact must be non-empty" "{\"verification\":{\"coverage\":{\"command\":\"c\",\"artifact\":\"\",\"parser\":\"istanbul\",\"baseline\":\"none\",\"min_line_pct\":80}}}" reject "artifact must be a non-empty string"
parity "preset must be a string"  "{\"verification\":{\"coverage\":{$COVB,\"baseline\":\"none\",\"min_line_pct\":80,\"preset\":null}}}" reject "preset must be a non-empty string"

# '..' is a SEGMENT rule, not a substring rule.
parity "dots inside a filename are fine" "{\"verification\":{\"coverage\":{\"command\":\"c\",\"artifact\":\"reports/v1..v2.json\",\"parser\":\"istanbul\",\"baseline\":\"none\",\"min_line_pct\":80}}}" ok
parity "a .. segment traverses" "{\"verification\":{\"coverage\":{\"command\":\"c\",\"artifact\":\"a/../../etc/x.json\",\"parser\":\"istanbul\",\"baseline\":\"none\",\"min_line_pct\":80}}}" reject "must not traverse"

# Structural: the schema DECLARES the cross-field rules the gate enforces.
COV_SCHEMA='.properties.verification.properties.coverage'
assert "schema declares 3 cross-field rules" \
    jq -e "$COV_SCHEMA.allOf | length == 3" "$SCHEMA"
assert "schema declares the floor-or-preset rule" \
    jq -e "$COV_SCHEMA.allOf[0].anyOf | map(.required[0]) | sort == [\"min_branch_pct\",\"min_line_pct\",\"preset\"]" "$SCHEMA"
assert "schema forbids regression under baseline none" \
    jq -e "$COV_SCHEMA.allOf[1].then.not.required == [\"max_regression_pct\"]" "$SCHEMA"
assert "schema requires a brownfield threshold source" \
    jq -e "$COV_SCHEMA.allOf[2].then.anyOf | map(.required[0]) | sort == [\"max_regression_pct\",\"preset\"]" "$SCHEMA"
# Non-empty string constraints must match the gate, or the schema documents
# a laxer contract than the thing that runs (#224 review, P3).
assert "schema requires non-empty command/artifact/preset" \
    jq -e "[$COV_SCHEMA.properties | .command, .artifact, .preset | .minLength] | all(. == 1)" "$SCHEMA"
assert "schema closes both objects" \
    jq -e '.properties.verification.additionalProperties == false and '"$COV_SCHEMA"'.additionalProperties == false' "$SCHEMA"

# ══════════════════════════════════════════════════════════════
echo "=== #242 C2: verification.conformance ==="
# ══════════════════════════════════════════════════════════════

CONF_APP='"command":"npm start","ready":{"url":"http://127.0.0.1:3123/health","timeout_sec":30},"stop_timeout_sec":10'

w n-ok.json "{\"schema_version\":2,\"profile\":\"pr\",\"verification\":{\"conformance\":{\"evaluator\":\"codex-eval\",\"timeout_sec\":600},\"app\":{$CONF_APP}}}"
assert "url-readiness conformance block is valid" bash "$V" "$TMP/n-ok.json"

w n-cmd.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"npm start","interface":"http://127.0.0.1:3123","ready":{"command":"curl -fsS http://127.0.0.1:3123/health","timeout_sec":30},"stop_timeout_sec":10}}}'
assert "command-readiness WITH app.interface is valid" bash "$V" "$TMP/n-cmd.json"

w n-both.json "{\"schema_version\":2,\"verification\":{\"coverage\":{$COV_OK},\"conformance\":{\"evaluator\":\"e\",\"timeout_sec\":600},\"app\":{$CONF_APP}}}"
assert "coverage and conformance compose" bash "$V" "$TMP/n-both.json"

# Command-only readiness with no interface starves the evaluator of an
# app address (#242 rev-4 finding 2).
w n-noiface.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"npm start","ready":{"command":"true","timeout_sec":30},"stop_timeout_sec":10}}}'
assert_rejects "command-only readiness without interface is rejected" "$TMP/n-noiface.json" "required when readiness is command-based"

w n-arr.json '{"schema_version":2,"verification":{"conformance":[]}}'
assert_rejects "conformance as an array is a violation, not a crash" "$TMP/n-arr.json" "conformance must be an object"

w n-unk.json "{\"schema_version\":2,\"verification\":{\"conformance\":{\"evaluator\":\"e\",\"timeout_sec\":600,\"bogus\":1},\"app\":{$CONF_APP}}}"
assert_rejects "unknown conformance key is rejected" "$TMP/n-unk.json" "unknown key 'verification.conformance.bogus'"

w n-noeval.json "{\"schema_version\":2,\"verification\":{\"conformance\":{\"timeout_sec\":600},\"app\":{$CONF_APP}}}"
assert_rejects "conformance.evaluator is required" "$TMP/n-noeval.json" "verification.conformance.evaluator is required"

w n-emptyeval.json "{\"schema_version\":2,\"verification\":{\"conformance\":{\"evaluator\":\"\",\"timeout_sec\":600},\"app\":{$CONF_APP}}}"
assert_rejects "empty evaluator is rejected" "$TMP/n-emptyeval.json" "evaluator must be a non-empty string"

w n-noto.json "{\"schema_version\":2,\"verification\":{\"conformance\":{\"evaluator\":\"e\"},\"app\":{$CONF_APP}}}"
assert_rejects "conformance.timeout_sec is required (no silent default)" "$TMP/n-noto.json" "timeout_sec is required"

w n-zeroto.json "{\"schema_version\":2,\"verification\":{\"conformance\":{\"evaluator\":\"e\",\"timeout_sec\":0},\"app\":{$CONF_APP}}}"
assert_rejects "non-positive conformance timeout is rejected" "$TMP/n-zeroto.json" "timeout_sec must be a positive INTEGER"

w n-noapp.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600}}}'
assert_rejects "conformance requires the shared verification.app" "$TMP/n-noapp.json" "verification.app is required when verification.conformance is present"

w n-appstr.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":"npm start"}}'
assert_rejects "app as a string is a violation, not a crash" "$TMP/n-appstr.json" "app must be an object"

w n-appunk.json "{\"schema_version\":2,\"verification\":{\"conformance\":{\"evaluator\":\"e\",\"timeout_sec\":600},\"app\":{$CONF_APP,\"extra\":1}}}"
assert_rejects "unknown app key is rejected" "$TMP/n-appunk.json" "unknown key 'verification.app.extra'"

w n-nocmd.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"ready":{"url":"http://x/h","timeout_sec":30},"stop_timeout_sec":10}}}'
assert_rejects "app.command is required" "$TMP/n-nocmd.json" "app.command is required"

w n-nostop.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","ready":{"url":"http://x/h","timeout_sec":30}}}}'
assert_rejects "app.stop_timeout_sec is required" "$TMP/n-nostop.json" "stop_timeout_sec is required and must be a positive INTEGER"

w n-emptyiface.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","interface":"","ready":{"url":"http://x/h","timeout_sec":30},"stop_timeout_sec":10}}}'
assert_rejects "empty interface is rejected" "$TMP/n-emptyiface.json" "interface must be a non-empty string"

w n-noready.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","stop_timeout_sec":10}}}'
assert_rejects "app.ready is required" "$TMP/n-noready.json" "app.ready is required"

w n-readyarr.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","ready":[],"stop_timeout_sec":10}}}'
assert_rejects "ready as an array is a violation, not a crash" "$TMP/n-readyarr.json" "ready must be an object"

w n-readyunk.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","ready":{"url":"http://x/h","timeout_sec":30,"extra":1},"stop_timeout_sec":10}}}'
assert_rejects "unknown ready key is rejected" "$TMP/n-readyunk.json" "unknown key 'verification.app.ready.extra'"

w n-readyboth.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","ready":{"url":"http://x/h","command":"true","timeout_sec":30},"stop_timeout_sec":10}}}'
assert_rejects "ready with BOTH url and command is rejected" "$TMP/n-readyboth.json" "exactly ONE of url | command (got both)"

w n-readynone.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","ready":{"timeout_sec":30},"stop_timeout_sec":10}}}'
assert_rejects "ready with NEITHER url nor command is rejected" "$TMP/n-readynone.json" "exactly ONE of url | command (got neither)"

w n-readyempty.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","ready":{"url":"","timeout_sec":30},"stop_timeout_sec":10}}}'
assert_rejects "empty ready.url is rejected" "$TMP/n-readyempty.json" "ready.url must be a non-empty string"

w n-readynoto.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","ready":{"url":"http://x/h"},"stop_timeout_sec":10}}}'
assert_rejects "ready.timeout_sec is required (bounded probe)" "$TMP/n-readynoto.json" "ready.timeout_sec is required and must be a positive INTEGER"

# ── Build-review round 5 finding 2: every conformance bound is integer
#    shell arithmetic, so a fractional value the schema accepted would be
#    uncomputable at the gate. Rejected by name, in all three places. ──
w b5-frac1.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":0.5},"app":{"command":"c","ready":{"url":"http://x/h","timeout_sec":5},"stop_timeout_sec":5}}}'
assert_rejects "fractional conformance.timeout_sec is rejected" "$TMP/b5-frac1.json" "timeout_sec must be a positive INTEGER"
w b5-frac2.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","ready":{"url":"http://x/h","timeout_sec":0.5},"stop_timeout_sec":5}}}'
assert_rejects "fractional ready.timeout_sec is rejected" "$TMP/b5-frac2.json" "ready.timeout_sec is required and must be a positive INTEGER"
w b5-frac3.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","ready":{"url":"http://x/h","timeout_sec":5},"stop_timeout_sec":2.5}}}'
assert_rejects "fractional stop_timeout_sec is rejected" "$TMP/b5-frac3.json" "stop_timeout_sec is required and must be a positive INTEGER"

# ── Build-review finding 1: the interface is bound to the launched
#    instance — probeable http(s), same origin as ready.url. ──
w b1-div.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","interface":"http://127.0.0.1:4000","ready":{"url":"http://127.0.0.1:3000/health","timeout_sec":5},"stop_timeout_sec":5}}}'
assert_rejects "divergent interface/ready origins are rejected" "$TMP/b1-div.json" "must equal ready.url's origin"

w b1-same.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","interface":"http://127.0.0.1:3000","ready":{"url":"http://127.0.0.1:3000/health","timeout_sec":5},"stop_timeout_sec":5}}}'
assert "same-origin interface + ready.url is valid" bash "$V" "$TMP/b1-same.json"

w b1-nonurl.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","interface":"port 4000","ready":{"command":"true","timeout_sec":5},"stop_timeout_sec":5}}}'
assert_rejects "non-URL interface is rejected (unprobeable)" "$TMP/b1-nonurl.json" "absolute http(s) URL"

w b1-badready.json '{"schema_version":2,"verification":{"conformance":{"evaluator":"e","timeout_sec":600},"app":{"command":"c","ready":{"url":"localhost:3000/health","timeout_sec":5},"stop_timeout_sec":5}}}'
assert_rejects "non-http ready.url is rejected" "$TMP/b1-badready.json" "must be an absolute http(s) URL"

# ── FR-2 derivation helper: required iff the artifact maps runtime_conformance ──
# shellcheck source=/dev/null
source "$REPO_DIR/scripts/lib/verification-common.sh"
cat > "$TMP/v-conf.yaml" <<'YAML'
status: finalized
FR-1:
  statement_sha: "sha256:aaaa"
  verifiers:
    - kind: deterministic
      test: "bash tests/x.sh"
FR-2:
  statement_sha: "sha256:bbbb"
  verifiers:
    - kind: runtime_conformance
      criterion: "cancel button aborts the job and the row shows cancelled"
YAML
cat > "$TMP/v-det.yaml" <<'YAML'
status: finalized
FR-1:
  statement_sha: "sha256:aaaa"
  verifiers:
    - kind: deterministic
      test: "bash tests/x.sh"
YAML
assert "derivation: runtime_conformance mapping derives true" \
    bash -c "source '$REPO_DIR/scripts/lib/verification-common.sh'; [[ \"\$(vc_conformance_required '$TMP/v-conf.yaml')\" == true ]]"
assert "derivation: deterministic-only artifact derives false" \
    bash -c "source '$REPO_DIR/scripts/lib/verification-common.sh'; [[ \"\$(vc_conformance_required '$TMP/v-det.yaml')\" == false ]]"
assert "derivation: missing artifact derives false (absence is not a requirement)" \
    bash -c "source '$REPO_DIR/scripts/lib/verification-common.sh'; [[ \"\$(vc_conformance_required '$TMP/no-such.yaml')\" == false ]]"

# Build-review finding 2: an EARLY mapping followed by a large record
# tail must still derive true under pipefail — the pre-fix consumer
# exited on first match, SIGPIPE'd the producer once the remaining
# records overflowed the pipe buffer, and the 141 pipeline status
# silently derived "false".
python3 - "$TMP/v-big.yaml" << 'PYEOF'
import sys
p = sys.argv[1]
with open(p, "w") as f:
    f.write("status: finalized\nfeature_id: demo\n\n")
    f.write('FR-1:\n  statement_sha: "sha256:aaaa"\n  verifiers:\n'
            '    - kind: runtime_conformance\n      criterion: "early mapping"\n')
    for i in range(2, 20002):
        f.write(f'FR-{i}:\n  statement_sha: "sha256:bbbb"\n  verifiers:\n'
                '    - kind: deterministic\n      test: "bash tests/x.sh"\n')
PYEOF
assert "derivation: early mapping in a large artifact derives true (no SIGPIPE truncation)" \
    bash -c "set -o pipefail; source '$REPO_DIR/scripts/lib/verification-common.sh'; [[ \"\$(vc_conformance_required '$TMP/v-big.yaml')\" == true ]]"

# ── schema parity: the schema DECLARES what the gate enforces ──
CONF_SCHEMA='.properties.verification.properties.conformance'
APP_SCHEMA='.properties.verification.properties.app'
assert "schema: conformance requires evaluator/timeout_sec (app moved up)" \
    jq -e "$CONF_SCHEMA.required | sort == [\"evaluator\",\"timeout_sec\"]" "$SCHEMA"
assert "schema: conformance no longer declares an app property" \
    jq -e "$CONF_SCHEMA.properties | has(\"app\") | not" "$SCHEMA"
assert "schema: conformance/app/ready are all closed" \
    jq -e "$CONF_SCHEMA.additionalProperties == false and $APP_SCHEMA.additionalProperties == false and $APP_SCHEMA.properties.ready.additionalProperties == false" "$SCHEMA"
assert "schema: app requires command/ready/stop_timeout_sec" \
    jq -e "$APP_SCHEMA.required | sort == [\"command\",\"ready\",\"stop_timeout_sec\"]" "$SCHEMA"
assert "schema: ready declares exactly-one url|command" \
    jq -e "$APP_SCHEMA.properties.ready.oneOf | map(.required[0]) | sort == [\"command\",\"url\"]" "$SCHEMA"
assert "schema: command-readiness requires interface (if/then)" \
    jq -e "$APP_SCHEMA.if.properties.ready.required == [\"command\"] and $APP_SCHEMA.then.required == [\"interface\"]" "$SCHEMA"
assert "schema: evaluator and interface are non-empty strings" \
    jq -e "[$CONF_SCHEMA.properties.evaluator.minLength, $APP_SCHEMA.properties.interface.minLength] | all(. == 1)" "$SCHEMA"
assert "schema: the three conformance bounds are integer-typed" \
    jq -e "[$CONF_SCHEMA.properties.timeout_sec, $APP_SCHEMA.properties.stop_timeout_sec, $APP_SCHEMA.properties.ready.properties.timeout_sec] | all(.type == \"integer\" and .minimum == 1)" "$SCHEMA"
assert "schema: interface and ready.url declare the http(s) pattern" \
    jq -e "[$APP_SCHEMA.properties.interface.pattern, $APP_SCHEMA.properties.ready.properties.url.pattern] | all(. == \"^https?://\")" "$SCHEMA"

# ══════════════════════════════════════════════════════════════
echo "=== #239 C3: verification.app + verification.visual ==="
# ══════════════════════════════════════════════════════════════
# The app moved OUT of conformance so one lifecycle serves both the
# evaluator and the visual harness; `visual` became a real block. Both
# were previously rejected by name as placeholders.

APP_OK='"command":"npm start","ready":{"url":"http://127.0.0.1:3000/health","timeout_sec":30},"stop_timeout_sec":10'
VIS_OK='"command":"npm ci && npm run copilot:review","artifact":"tmp/ui-review/critique-feedback.json","url":"http://127.0.0.1:3000/","timeout_sec":600'

w v-ok.json "{\"schema_version\":2,\"profile\":\"pr\",\"verification\":{\"app\":{$APP_OK},\"visual\":{$VIS_OK}}}"
assert "a visual block with a shared app is valid" bash "$V" "$TMP/v-ok.json"

w v-skipfalse.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"visual\":{$VIS_OK,\"skip_is_failure\":false}}}"
assert "skip_is_failure may be set explicitly" bash "$V" "$TMP/v-skipfalse.json"

w v-both.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"conformance\":{\"evaluator\":\"e\",\"timeout_sec\":600},\"visual\":{$VIS_OK}}}"
assert "conformance and visual share ONE app block" bash "$V" "$TMP/v-both.json"

# The requirement is DERIVED from verification.yaml, never operator-set.
w v-rwuis.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"visual\":{$VIS_OK,\"required_when_ui_in_scope\":true}}}"
assert_rejects "required_when_ui_in_scope is rejected by name" "$TMP/v-rwuis.json" "required_when_ui_in_scope is DERIVED from verification.yaml"

# The old app location is refused BY NAME with a migration message — an
# ignored block would leave the operator's launch command inert.
w v-oldapp.json "{\"schema_version\":2,\"verification\":{\"conformance\":{\"evaluator\":\"e\",\"timeout_sec\":600,\"app\":{$APP_OK}}}}"
assert_rejects "verification.conformance.app is refused with a migration message" "$TMP/v-oldapp.json" "has MOVED to verification.app"

# Each consumer requires the app: a gate with nothing to point at cannot run.
w v-noapp.json "{\"schema_version\":2,\"verification\":{\"visual\":{$VIS_OK}}}"
assert_rejects "visual without verification.app is rejected" "$TMP/v-noapp.json" "verification.app is required when verification.visual is present"

for req in command artifact url; do
    w "v-no-$req.json" "$(python3 - "$req" << 'PYEOF'
import json,sys
vis={"command":"npm run copilot:review","artifact":"tmp/ui/f.json","url":"http://127.0.0.1:3000/","timeout_sec":600}
vis.pop(sys.argv[1])
app={"command":"npm start","ready":{"url":"http://127.0.0.1:3000/health","timeout_sec":30},"stop_timeout_sec":10}
print(json.dumps({"schema_version":2,"verification":{"app":app,"visual":vis}}))
PYEOF
)"
    assert_rejects "visual.$req is required" "$TMP/v-no-$req.json" "verification.visual.$req is required"
done

w v-noto.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"visual\":{\"command\":\"c\",\"artifact\":\"a.json\",\"url\":\"http://127.0.0.1:3000/\"}}}"
assert_rejects "visual.timeout_sec is required (no silent default)" "$TMP/v-noto.json" "verification.visual.timeout_sec is required"

w v-fracto.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"visual\":{$VIS_OK}}}"
python3 -c "
import json;p='$TMP/v-fracto.json';d=json.load(open(p));d['verification']['visual']['timeout_sec']=1.5;json.dump(d,open(p,'w'))"
assert_rejects "fractional visual.timeout_sec is rejected" "$TMP/v-fracto.json" "positive INTEGER"

w v-skipstr.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"visual\":{$VIS_OK,\"skip_is_failure\":\"no\"}}}"
assert_rejects "non-boolean skip_is_failure is rejected" "$TMP/v-skipstr.json" "skip_is_failure must be a boolean"

w v-unk.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"visual\":{$VIS_OK,\"bogus\":1}}}"
assert_rejects "unknown visual key is rejected" "$TMP/v-unk.json" "unknown key 'verification.visual.bogus'"

w v-visarr.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"visual\":[]}}"
assert_rejects "visual as an array is a violation, not a crash" "$TMP/v-visarr.json" "verification.visual must be an object"

# artifact: the C1 containment rule, lexically at config time.
w v-abs.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"visual\":{\"command\":\"c\",\"artifact\":\"/tmp/f.json\",\"url\":\"http://127.0.0.1:3000/\",\"timeout_sec\":600}}}"
assert_rejects "absolute visual.artifact is rejected" "$TMP/v-abs.json" "must be a relative path inside the project"

w v-esc.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"visual\":{\"command\":\"c\",\"artifact\":\"../f.json\",\"url\":\"http://127.0.0.1:3000/\",\"timeout_sec\":600}}}"
assert_rejects "traversing visual.artifact is rejected" "$TMP/v-esc.json" "must not traverse outside the project"

for ok in "reports/v1..v2.json" "..cache/ui-result.json"; do
    python3 - "$TMP/v-ok.json" "$TMP/v-artok.json" "$ok" << 'PYEOF'
import json, sys
d = json.load(open(sys.argv[1])); d["verification"]["visual"]["artifact"] = sys.argv[3]
json.dump(d, open(sys.argv[2], "w"))
PYEOF
    assert "contained artifact '$ok' is accepted (a '..' SEGMENT traverses, '..' in a name does not)" bash "$V" "$TMP/v-artok.json"
done

# url: FROZEN browser base, never derived — but it must address the
# instance the driver launches (FR-12).
w v-badurl.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"visual\":{\"command\":\"c\",\"artifact\":\"a.json\",\"url\":\"localhost:3000\",\"timeout_sec\":600}}}"
assert_rejects "non-http visual.url is rejected" "$TMP/v-badurl.json" "must be an absolute http(s) URL"

w v-xorigin.json "{\"schema_version\":2,\"verification\":{\"app\":{$APP_OK},\"visual\":{\"command\":\"c\",\"artifact\":\"a.json\",\"url\":\"http://127.0.0.1:4000/\",\"timeout_sec\":600}}}"
assert_rejects "cross-origin visual.url is rejected" "$TMP/v-xorigin.json" "must equal the app's origin"

# Same-origin against a COMMAND-readiness app resolves via app.interface.
w v-iface.json '{"schema_version":2,"verification":{"app":{"command":"npm start","interface":"http://127.0.0.1:3000","ready":{"command":"true","timeout_sec":30},"stop_timeout_sec":10},"visual":{"command":"c","artifact":"a.json","url":"http://127.0.0.1:3000/dashboard","timeout_sec":600}}}'
assert "visual.url same-origin with app.interface is valid" bash "$V" "$TMP/v-iface.json"

# ── THE RELOCATION ITSELF (#239 FR-10): the exact C2 config fails with
#    the migration diagnostic, and its MECHANICALLY relocated equivalent
#    passes — same app object, moved up one level, nothing else changed.
#    This pair is what proves the move neither weakened nor strengthened
#    C2's app contract; separate accept/reject cases would not.
C2_APP='"command":"npm start","interface":"http://127.0.0.1:3123","ready":{"url":"http://127.0.0.1:3123/health","timeout_sec":30},"stop_timeout_sec":10'

w v-c2-legacy.json "{\"schema_version\":2,\"profile\":\"pr\",\"verification\":{\"conformance\":{\"evaluator\":\"codex-eval\",\"timeout_sec\":30,\"app\":{$C2_APP}}}}"
assert_rejects "the exact C2 config now fails with the migration diagnostic" "$TMP/v-c2-legacy.json" "verification.conformance.app has MOVED to verification.app"

w v-c2-moved.json "{\"schema_version\":2,\"profile\":\"pr\",\"verification\":{\"app\":{$C2_APP},\"conformance\":{\"evaluator\":\"codex-eval\",\"timeout_sec\":30}}}"
assert "the mechanically relocated C2 config is valid" bash "$V" "$TMP/v-c2-moved.json"

# ...and the relocated block still enforces every C2 app rule. Each
# mutation is applied to the MOVED config, so a rule lost in the move
# shows up here rather than in a passing accept-case.
mut_moved() {  # <name> <python-mutation-on-d["verification"]["app"]> <expected>
    python3 - "$TMP/v-c2-moved.json" "$TMP/$1.json" "$2" << 'PYEOF'
import json, sys
d = json.load(open(sys.argv[1])); app = d["verification"]["app"]
exec(sys.argv[3])
json.dump(d, open(sys.argv[2], "w"))
PYEOF
    assert_rejects "relocated app still enforces: $1" "$TMP/$1.json" "$3"
}
mut_moved r-nocmd    'del app["command"]'                        "verification.app.command is required"
mut_moved r-nostop   'del app["stop_timeout_sec"]'               "verification.app.stop_timeout_sec is required"
mut_moved r-fracstop 'app["stop_timeout_sec"]=2.5'               "positive INTEGER"
mut_moved r-noready  'del app["ready"]'                          "verification.app.ready is required"
mut_moved r-bothready 'app["ready"]["command"]="true"'           "exactly ONE of url | command (got both)"
mut_moved r-noreadyto 'del app["ready"]["timeout_sec"]'          "verification.app.ready.timeout_sec is required"
mut_moved r-unkkey   'app["extra"]=1'                            "unknown key 'verification.app.extra'"
mut_moved r-badiface 'app["interface"]="port 3123"'              "absolute http(s) URL"
mut_moved r-xorigin  'app["interface"]="http://127.0.0.1:4000"'  "must equal ready.url's origin"
mut_moved r-cmdready 'app["ready"]={"command":"true","timeout_sec":30}; del app["interface"]' "required when readiness is command-based"

# Schema parity for the new block.
VIS_SCHEMA='.properties.verification.properties.visual'
assert "schema: verification accepts app and visual" \
    jq -e '.properties.verification.properties | has("app") and has("visual")' "$SCHEMA"
assert "schema: visual requires command/artifact/url/timeout_sec" \
    jq -e "$VIS_SCHEMA.required | sort == [\"artifact\",\"command\",\"timeout_sec\",\"url\"]" "$SCHEMA"
assert "schema: visual is closed" \
    jq -e "$VIS_SCHEMA.additionalProperties == false" "$SCHEMA"
assert "schema: visual.timeout_sec is integer-typed with minimum 1" \
    jq -e "$VIS_SCHEMA.properties.timeout_sec | .type == \"integer\" and .minimum == 1" "$SCHEMA"
assert "schema: skip_is_failure defaults to true" \
    jq -e "$VIS_SCHEMA.properties.skip_is_failure | .type == \"boolean\" and .default == true" "$SCHEMA"
# PARITY: every rule the jq validator enforces must also be expressible
# in the schema, or the two disagree about what a valid config is.
assert "schema: visual.url declares the http(s) pattern (validator parity)" \
    jq -e "$VIS_SCHEMA.properties.url.pattern == \"^https?://\"" "$SCHEMA"
assert "schema: conformance OR visual requires app (validator parity)" \
    jq -e '.properties.verification.allOf
           | any(.if.anyOf == [{"required":["conformance"]},{"required":["visual"]}]
                 and .then.required == ["app"])' "$SCHEMA"

# ── review block validation ──────────────────────────────────
# max_rounds and loop_timeout_sec are COUNTS — the runtime
# silently falls back to its default for anything that is not a
# positive integer.  The validator enforces the shape only when
# the value IS numeric; non-numeric values (strings, booleans)
# pass through to the driver's runtime fallback.

w rev1.json '{"review":{"max_rounds":1.5}}'
assert_rejects "fractional max_rounds is rejected" "$TMP/rev1.json" "positive integer"

w rev2.json '{"review":{"max_rounds":0}}'
assert_rejects "zero max_rounds is rejected" "$TMP/rev2.json" "positive integer"

w rev3.json '{"review":{"max_rounds":"abc"}}'
assert "string max_rounds passes through for driver fallback" bash "$V" "$TMP/rev3.json"

w rev4.json '{"review":{"loop_timeout_sec":1.5}}'
assert_rejects "fractional loop_timeout_sec is rejected" "$TMP/rev4.json" "positive integer"

assert "schema max_rounds is integer type" \
    jq -e '.properties.review.properties.max_rounds.type == "integer"' "$SCHEMA"
assert "schema max_rounds has minimum 1" \
    jq -e '.properties.review.properties.max_rounds.minimum == 1' "$SCHEMA"
assert "schema loop_timeout_sec is integer type" \
    jq -e '.properties.review.properties.loop_timeout_sec.type == "integer"' "$SCHEMA"
assert "schema loop_timeout_sec has minimum 1" \
    jq -e '.properties.review.properties.loop_timeout_sec.minimum == 1' "$SCHEMA"

echo ""
echo "========================================="
echo "  automation-config tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_AUTOMATION_CONFIG_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_AUTOMATION_CONFIG_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]

