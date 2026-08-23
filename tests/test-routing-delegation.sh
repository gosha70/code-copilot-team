#!/usr/bin/env bash
# test-routing-delegation.sh — #254 (increment C of #109) execution
# surfaces. T3: route-class-aware selection legality over B's frozen
# oracle — absent argument is B byte-identical (the unmodified
# routing-failover suite is the primary gate; this suite pins the
# class semantics), route classes only remove candidates or
# restructure tier precedence, within-tier total order untouched,
# tier2_fallback unlocked ONLY by the permanent-exhaustion shape.
#
# Run from the repo root: bash tests/test-routing-delegation.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
CLIB="$REPO_DIR/scripts/lib/routing-config.sh"
SELLIB="$REPO_DIR/scripts/lib/routing-select.sh"
STLIB="$REPO_DIR/scripts/lib/routing-state.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/cct-rdel.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0
assert() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name"; fi
}
assert_eq() {
    local name="$1" want="$2" got="$3"
    if [[ "$want" == "$got" ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected '$want', got '$got')"; fi
}

# six profiles: three tier1 (t1a/t1c tie at priority 10 — id breaks;
# t1b at 20) and three tier2 (t2c pri 1 WITHOUT the build role, t2b
# pri 5, t2a pri 10)
REG="$TMP/routing.toml"
cat > "$REG" <<'REOF'
schema_version = 1

[policy]
enabled = true

[route_classes.tier1_only]
tier_order = ["tier1"]

[[profiles]]
id = "t1a"
backend = "claude-code"
provider = "anthropic-subscription"
model = "sonnet"
capability_tier = "tier1"
priority = 10
quota_pool = "poolA"
roles = ["build", "reconcile"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_mode = "claude-login"

[[profiles]]
id = "t1b"
backend = "claude-code"
provider = "deepseek-platform"
model = "deepseek-chat"
capability_tier = "tier1"
priority = 20
quota_pool = "poolB"
roles = ["build"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_env = "CCT_DS_KEY"

[[profiles]]
id = "t1c"
backend = "claude-code"
provider = "anthropic-api"
model = "sonnet"
capability_tier = "tier1"
priority = 10
quota_pool = "poolC"
roles = ["build"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_env = "CCT_API_KEY"

[[profiles]]
id = "t2a"
backend = "pi"
provider = "local-ollama"
model = "qwen-coder"
capability_tier = "tier2"
priority = 10
quota_pool = "poolL"
roles = ["build", "bounded-build"]
tool_profile = "local-builder-minimal"
data_policy = "local-only"
credential_env = "CCT_LOCAL_KEY"

[[profiles]]
id = "t2b"
backend = "pi"
provider = "local-ollama"
model = "qwen-coder-large"
capability_tier = "tier2"
priority = 5
quota_pool = "poolL"
roles = ["build", "bounded-build"]
tool_profile = "local-builder-minimal"
data_policy = "local-only"
credential_env = "CCT_LOCAL_KEY"

[[profiles]]
id = "t2c"
backend = "pi"
provider = "local-ollama"
model = "qwen-mini"
capability_tier = "tier2"
priority = 1
quota_pool = "poolL"
roles = ["bounded-build"]
tool_profile = "local-builder-minimal"
data_policy = "local-only"
credential_env = "CCT_LOCAL_KEY"
REOF
EFF=$( ( set +e; source "$CLIB"; rc_effective "$REG" - ) )
# circuit-state until values are EPOCH SECONDS (rs_set_* contract)
NOW=$(date -u +%s)
U1=$(( NOW + 1800 ))
U2=$(( NOW + 3600 ))

RT() {  # <state-file> <attempted-json> <route-class-or--> [role]
    local cls="$3"; [[ "$cls" == "-" ]] && cls=""
    if [[ -z "$cls" ]]; then
        ( set +e; CCT_ROUTING_STATE="$1" source "$SELLIB"; rt_select "$EFF" "$2" "${4:-build}" )
    else
        ( set +e; CCT_ROUTING_STATE="$1" source "$SELLIB"; rt_select "$EFF" "$2" "${4:-build}" "$cls" )
    fi
}
ST() {  # <state-file> <fn> <args>...
    ( set +e; CCT_ROUTING_STATE="$1" source "$STLIB"; "${@:2}" ) >/dev/null 2>&1
}
verdict_of() { jq -r --arg id "$2" '.considered[] | select(.id == $id) | .verdict' <<< "$1"; }
reason_of()  { jq -r --arg id "$2" '.considered[] | select(.id == $id) | .reason'  <<< "$1"; }

echo "== T3.1: compatibility + closed vocabulary =="

A=$(RT "$TMP/c1.json" '[]' -)
B=$(RT "$TMP/c1.json" '[]' tier1_only)
assert_eq "tier1_only output is byte-identical to the absent argument" "$A" "$B"
assert_eq "absent class: B behavior — best tier1 selected" "t1a" "$(jq -r '.selected.id' <<< "$A")"
assert "absent class: tier2 keeps B's exact never-selected message" \
    grep -q "increment B routes tier1 only — tier2 is never selected (Tier-2 selection is increment C)" <<< "$(reason_of "$A" t2a)"
OUT=$(RT "$TMP/c1.json" '[]' tier9_wild 2>&1) && rc=0 || rc=$?
assert_eq "unknown route class refused (rc 1)" "1" "$rc"
assert "unknown route class refusal names the closed vocabulary" \
    grep -q "not in the closed vocabulary" <<< "$OUT"
assert_eq "every candidate carries a verdict (absent class)" "6" "$(jq '.considered | length' <<< "$A")"

echo ""
echo "== T3.2: primary_only =="

P=$(RT "$TMP/p1.json" '[]' primary_only)
assert_eq "primary = total-order-first tier1 (priority tie -> id lexical)" "t1a" "$(jq -r '.selected.id' <<< "$P")"
assert "tie peer rejected by the primary restriction" \
    grep -q "route class 'primary_only' admits only the primary candidate 't1a'" <<< "$(reason_of "$P" t1c)"
assert "lower-priority tier1 rejected by the primary restriction" \
    grep -q "admits only the primary candidate 't1a'" <<< "$(reason_of "$P" t1b)"
assert "tier2 never reached under primary_only" \
    grep -q "route class 'primary_only' never reaches tier2" <<< "$(reason_of "$P" t2a)"

ST "$TMP/p2.json" rs_set_profile p2-1 t1a cooldown rate "$U1"
P=$(RT "$TMP/p2.json" '[]' primary_only)
assert_eq "cooling primary: selected stays null (never 'next best')" "null" "$(jq -r '.selected' <<< "$P")"
assert_eq "cooling primary: TEMPORARY shape with the primary's until" "$U1" "$(jq -r '.earliest_retry' <<< "$P")"
assert_eq "cooling primary: terminal_reason null" "null" "$(jq -r '.terminal_reason' <<< "$P")"

ST "$TMP/p3.json" rs_set_profile p3-1 t1a disabled auth -
P=$(RT "$TMP/p3.json" '[]' primary_only)
assert_eq "disabled primary: PERMANENT exhaustion despite healthy peers" \
    "routing_no_eligible_profile" "$(jq -r '.terminal_reason' <<< "$P")"
P=$(RT "$TMP/p4.json" '["t1a"]' primary_only)
assert_eq "attempted primary: PERMANENT exhaustion (request-local)" \
    "routing_no_eligible_profile" "$(jq -r '.terminal_reason' <<< "$P")"

echo ""
echo "== T3.3: tier2_fallback — the pinned unlock predicate =="

F=$(RT "$TMP/f1.json" '[]' tier2_fallback)
assert_eq "healthy tier1: tier1 selected, tier2 stays locked" "t1a" "$(jq -r '.selected.id' <<< "$F")"
assert "locked tier2 names the never-weakened tier requirement" \
    grep -q "tier2 locked — tier1 is not permanently exhausted" <<< "$(reason_of "$F" t2b)"

ST "$TMP/f2.json" rs_set_profile f2-1 t1a cooldown rate "$U2"
ST "$TMP/f2.json" rs_set_profile f2-2 t1b cooldown rate "$U1"
ST "$TMP/f2.json" rs_set_profile f2-3 t1c cooldown rate "$U2"
F=$(RT "$TMP/f2.json" '[]' tier2_fallback)
assert_eq "ALL tier1 cooling: TEMPORARY shape — tier2 does NOT unlock" "null" "$(jq -r '.selected' <<< "$F")"
assert_eq "temporary exhaustion waits to the earliest until" "$U1" "$(jq -r '.earliest_retry' <<< "$F")"
assert_eq "temporary exhaustion carries no terminal reason" "null" "$(jq -r '.terminal_reason' <<< "$F")"
assert "tier2 locked while tier1 merely cools" \
    grep -q "tier2 locked" <<< "$(reason_of "$F" t2b)"

F=$(RT "$TMP/f3.json" '["t1a","t1b","t1c"]' tier2_fallback)
assert_eq "tier1 permanently exhausted: tier2 unlocks, best tier2 selected" "t2b" "$(jq -r '.selected.id' <<< "$F")"
assert "unlocked tier2 still enforces the role filter (t2c has no build role)" \
    grep -q "does not hold role 'build'" <<< "$(reason_of "$F" t2c)"
assert_eq "within tier2 the total order holds (t2a eligible behind t2b)" \
    "eligible" "$(verdict_of "$F" t2a)"

ST "$TMP/f4.json" rs_set_pool f4-1 poolL cooldown exhausted "$U2"
F=$(RT "$TMP/f4.json" '["t1a","t1b","t1c"]' tier2_fallback)
assert_eq "unlocked-but-cooling tier2: TEMPORARY shape with tier2's until" "$U2" "$(jq -r '.earliest_retry' <<< "$F")"
F=$(RT "$TMP/f5.json" '["t1a","t1b","t1c","t2a","t2b","t2c"]' tier2_fallback)
assert_eq "everything out: PERMANENT routing_no_eligible_profile" \
    "routing_no_eligible_profile" "$(jq -r '.terminal_reason' <<< "$F")"
F=$(RT "$TMP/f6.json" '["t1a","t1b","t1c","t2b"]' tier2_fallback)
assert_eq "tier2 order after t2b attempted: t2a is next by priority" "t2a" "$(jq -r '.selected.id' <<< "$F")"

echo ""
echo "== T3.4: tier2_preferred =="

R=$(RT "$TMP/r1.json" '[]' tier2_preferred)
assert_eq "tier2 first by policy: best ELIGIBLE tier2 selected (t2c role-rejected, t2b wins)" \
    "t2b" "$(jq -r '.selected.id' <<< "$R")"
assert_eq "tier1 evaluated as fallback, not rejected" "eligible" "$(verdict_of "$R" t1a)"
assert_eq "considered[] order: tier2 sorted, then tier1 sorted (no within-tier reorder)" \
    "t2c t2b t2a t1a t1c t1b" "$(jq -r '[.considered[].id] | join(" ")' <<< "$R")"

R=$(RT "$TMP/r2.json" '["t2a","t2b","t2c"]' tier2_preferred)
assert_eq "tier2 out: tier1 fallback selects t1a" "t1a" "$(jq -r '.selected.id' <<< "$R")"
ST "$TMP/r3.json" rs_set_pool r3-1 poolL cooldown exhausted "$U2"
R=$(RT "$TMP/r3.json" '[]' tier2_preferred)
assert_eq "tier2 cooling + tier1 healthy: falls back NOW (no wait)" "t1a" "$(jq -r '.selected.id' <<< "$R")"
assert_eq "selected shape carries no sleep target" "null" "$(jq -r '.earliest_retry' <<< "$R")"
ST "$TMP/r4.json" rs_set_pool r4-1 poolL cooldown exhausted "$U2"
ST "$TMP/r4.json" rs_set_profile r4-2 t1a cooldown rate "$U1"
ST "$TMP/r4.json" rs_set_profile r4-3 t1b cooldown rate "$U2"
ST "$TMP/r4.json" rs_set_profile r4-4 t1c cooldown rate "$U2"
R=$(RT "$TMP/r4.json" '[]' tier2_preferred)
assert_eq "both tiers cooling: TEMPORARY with the minimum until" "$U1" "$(jq -r '.earliest_retry' <<< "$R")"
R=$(RT "$TMP/r5.json" '["t1a","t1b","t1c","t2a","t2b","t2c"]' tier2_preferred)
assert_eq "all out: PERMANENT routing_no_eligible_profile" \
    "routing_no_eligible_profile" "$(jq -r '.terminal_reason' <<< "$R")"

echo ""
echo "== T3.5: shape invariants across classes =="

S=$(RT "$TMP/s1.json" '[]' tier2_preferred)
assert_eq "selected shape: exhausted=false" "false" "$(jq -r '.exhausted' <<< "$S")"
assert_eq "selected shape: terminal null" "null" "$(jq -r '.terminal_reason' <<< "$S")"
assert_eq "fallback path: every candidate carries exactly one verdict" "6" \
    "$(RT "$TMP/s2.json" '["t1a","t1b","t1c"]' tier2_fallback | jq '.considered | length')"
assert_eq "preferred path: every candidate carries exactly one verdict" "6" \
    "$(RT "$TMP/s3.json" '[]' tier2_preferred | jq '.considered | length')"
assert_eq "primary path: every candidate carries exactly one verdict" "6" \
    "$(RT "$TMP/s4.json" '[]' primary_only | jq '.considered | length')"

echo ""
echo "========================================="
echo "  routing-delegation tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_DELEGATION_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_DELEGATION_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
