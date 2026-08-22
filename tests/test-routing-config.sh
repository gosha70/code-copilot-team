#!/usr/bin/env bash
# test-routing-config.sh — #248 (increment A of #109) T1: the
# execution-profile registry. Constrained-TOML grammar (reject, never
# approximate), closed registry shape, credential-reference hygiene.
#
# Run from the repo root: bash tests/test-routing-config.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
LIB="$REPO_DIR/scripts/lib/routing-config.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/cct-routing.XXXXXX")"
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
rv() { ( set +e; source "$LIB"; rc_validate "$1" ); }
assert_reject() {  # <name> <file> <needle>
    local name="$1" file="$2" needle="$3" out rc=0
    out="$(rv "$file" 2>&1)" || rc=$?
    if [[ $rc -eq 1 && "$out" == *"$needle"* ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (rc=$rc)"; echo "$out" | sed 's/^/    /'; fi
}

# A minimal VALID registry; reject cases derive from it by sed.
GOOD="$TMP/good.toml"
cat > "$GOOD" <<'EOF'
schema_version = 1

[policy]
enabled = true
preferred_profile = "alpha"

[route_classes.tier1_only]
tier_order = ["tier1"]

[route_classes.tier2_fallback]
tier_order = ["tier1", "tier2"]

[[profiles]]
id = "alpha"
backend = "claude-code"
provider = "anthropic-subscription"
model = "sonnet"
capability_tier = "tier1"
priority = 10
quota_pool = "anthropic-subscription"
roles = ["build", "reconcile", "land"]
tool_profile = "full-cct"
credential_mode = "claude-login"
data_policy = "approved-cloud"

[[profiles]]
id = "alpha-opus"
backend = "claude-code"
provider = "anthropic-subscription"
model = "opus"
capability_tier = "tier1"
priority = 20
quota_pool = "anthropic-subscription"
roles = ["build"]
tool_profile = "full-cct"
credential_mode = "claude-login"
data_policy = "approved-cloud"

[[profiles]]
id = "local-t2"
backend = "claude-code"
provider = "local-vllm"
model = "qwen3-coder-next"
capability_tier = "tier2"
priority = 10
quota_pool = "local-vllm"
roles = ["bounded-build"]
tool_profile = "local-builder-minimal"
base_url_env = "CCT_LOCAL_ANTHROPIC_BASE_URL"
credential_env = "CCT_LOCAL_API_KEY"
data_policy = "local-only"
EOF
mut() {  # <out-name> <sed-expr...> -> path
    local out="$TMP/$1"; shift
    sed "$@" "$GOOD" > "$out"; printf '%s' "$out"
}

echo "=== routing-config registry tests (#248 T1) ==="

# ── SC-A1: the valid registry, field addressability ──
assert "the good registry validates" rv "$GOOD"
assert "the shipped example template validates" rv "$REPO_DIR/shared/templates/routing/routing.toml.example"

source "$LIB"
rc_parse "$GOOD" || true
assert_eq "vocabulary: backend is addressable"  "claude-code"             "$(rc_get profiles.0 backend)"
assert_eq "vocabulary: provider is addressable" "anthropic-subscription"  "$(rc_get profiles.0 provider)"
assert_eq "vocabulary: model is addressable"    "sonnet"                  "$(rc_get profiles.0 model)"
assert_eq "vocabulary: tier is addressable"     "tier1"                   "$(rc_get profiles.0 capability_tier)"
assert_eq "vocabulary: priority is addressable" "10"                      "$(rc_get profiles.0 priority)"
assert_eq "two profiles share one quota pool (pool != provider identity)" \
    "$(rc_get profiles.0 quota_pool)" "$(rc_get profiles.1 quota_pool)"
assert_eq "tier2 profile carries its own pool" "local-vllm" "$(rc_get profiles.2 quota_pool)"
assert_eq "route classes enumerate" "tier1_only tier2_fallback" "$(rc_route_classes | sort | tr '\n' ' ' | sed 's/ $//')"
assert_eq "roles array round-trips" "bounded-build" "$(rc_array_elems profiles.2 roles)"
assert_eq "tiers are the closed framework set" "tier1 tier2" "$RC_TIERS"

# ── SC-A2 grammar: reject, never approximate — each construct BY NAME ──
F="$TMP/g-dupkey.toml";   sed 's/^model = "opus"$/model = "opus"\nmodel = "opus"/' "$GOOD" > "$F"
assert_reject "grammar: duplicate key in a table" "$F" "duplicate key 'model'"
F="$TMP/g-duptable.toml"; cat "$GOOD" > "$F"; printf '\n[policy]\nenabled = false\n' >> "$F"
assert_reject "grammar: duplicate table declaration" "$F" "duplicate table declaration: [policy]"
F=$(mut g-dotted.toml 's/^tool_profile = "full-cct"$/tool.profile = "full-cct"/')
assert_reject "grammar: dotted keys" "$F" "dotted keys are not accepted"
F=$(mut g-inline.toml 's/^enabled = true$/limits = { max = 3 }/')
assert_reject "grammar: inline tables" "$F" "inline tables are not accepted"
F=$(mut g-multiline.toml 's/^model = "sonnet"$/model = """sonnet"""/')
assert_reject "grammar: multiline strings" "$F" "multiline strings are not accepted"
F=$(mut g-literal.toml "s/^model = \"sonnet\"\$/model = 'sonnet'/")
assert_reject "grammar: literal (single-quoted) strings" "$F" "literal (single-quoted) strings are not accepted"
F=$(mut g-nonstr.toml 's/^tier_order = \["tier1"\]$/tier_order = [1, 2]/')
assert_reject "grammar: non-string arrays" "$F" "only single-line arrays of basic strings"
F=$(mut g-quote.toml 's/^model = "sonnet"$/model = "sonnet/')
assert_reject "grammar: malformed quoting" "$F" "malformed quoting"
F=$(mut g-unrec.toml 's/^enabled = true$/enabled equals true/')
assert_reject "grammar: unrecognized line" "$F" "unrecognized line"
F=$(mut g-aot.toml 's/^\[\[profiles\]\]$/[[reviewers]]/')
assert_reject "grammar: other array-of-tables" "$F" "array-of-tables other than [[profiles]] is not accepted"
F=$(mut g-table.toml 's/^\[policy\]$/[polices]/')
assert_reject "grammar: unknown table" "$F" "table [polices] is not accepted"
F=$(mut g-root.toml 's/^schema_version = 1$/schema_version = 1\nstray = "x"/')
assert_reject "grammar: key outside any table" "$F" "outside any table"
F=$(mut g-nosv.toml '/^schema_version = 1$/d')
assert_reject "schema_version is required" "$F" "schema_version = 1 is required"
F=$(mut g-badsv.toml 's/^schema_version = 1$/schema_version = 2/')
assert_reject "unsupported schema_version" "$F" "is not supported"

# one run names MULTIPLE violations (parse continues past errors)
F="$TMP/g-multi.toml"; sed -e 's/^tool_profile = "full-cct"$/tool.profile = "full-cct"/' -e "s/^model = \"opus\"\$/model = 'opus'/" "$GOOD" > "$F"
OUT=$(rv "$F" 2>&1) || true
assert "multi-error: dotted key named"   grep -q "dotted keys are not accepted" <<< "$OUT"
assert "multi-error: literal string named in the SAME run" grep -q "literal (single-quoted) strings" <<< "$OUT"

# ── SC-A2 semantic: closed shape BY NAME ──
F=$(mut s-unk.toml 's/^tool_profile = "full-cct"$/tool_profile = "full-cct"\nshiny = "yes"/')
assert_reject "closed shape: unknown profile key" "$F" "unknown key 'shiny'"
F=$(mut s-missing.toml '/^provider = "local-vllm"$/d')
assert_reject "closed shape: missing required key" "$F" "missing required key 'provider'"
F=$(mut s-tier.toml 's/^capability_tier = "tier2"$/capability_tier = "tier7"/')
assert_reject "closed tiers: tier7 refused" "$F" "tiers are closed"
F=$(mut s-prio.toml 's/^priority = 20$/priority = "high"/')
assert_reject "priority must be a positive integer" "$F" "priority must be a positive integer"
F=$(mut s-dupid.toml 's/^id = "alpha-opus"$/id = "alpha"/')
assert_reject "duplicate profile id" "$F" "duplicate profile id 'alpha'"
F=$(mut s-role.toml 's/^roles = \["bounded-build"\]$/roles = ["bounded-build", "deploy"]/')
assert_reject "unknown role" "$F" "unknown role 'deploy'"
F=$(mut s-rcuk.toml 's/^tier_order = \["tier1", "tier2"\]$/tier_order = ["tier1", "tier9"]/')
assert_reject "route class references unknown tier" "$F" "unknown tier 'tier9'"
F=$(mut s-rcempty.toml 's/^tier_order = \["tier1"\]$/tier_order = []/')
assert_reject "empty tier_order" "$F" "must not be empty"
F=$(mut s-rcdup.toml 's/^tier_order = \["tier1", "tier2"\]$/tier_order = ["tier1", "tier1"]/')
assert_reject "repeated tier in tier_order" "$F" "repeats 'tier1'"
F=$(mut s-rckey.toml 's/^tier_order = \["tier1"\]$/tier_order = ["tier1"]\nfallback = "x"/')
assert_reject "route class unknown key" "$F" "unknown key 'fallback'"
F=$(mut s-url.toml 's|^base_url_env = "CCT_LOCAL_ANTHROPIC_BASE_URL"$|base_url = "ftp://host/x"|')
assert_reject "base_url must be http(s)" "$F" "absolute http(s) URL"
F=$(mut s-polkey.toml 's/^enabled = true$/enabled = true\nprobe_cmd = "curl"/')
assert_reject "policy unknown key" "$F" "[policy] unknown key 'probe_cmd'"
F=$(mut s-polfuture.toml 's/^enabled = true$/enabled = true\nfailback = "next-task-boundary"/')
assert_reject "policy: future behavior-bearing key is refused, not inert" "$F" "not supported in increment A"
F=$(mut s-polfuture2.toml 's/^enabled = true$/enabled = true\nmax_switches_per_task = 3/')
assert_reject "policy: every future key carries the refusal (not just one)" "$F" "not supported in increment A"
F=$(mut s-pref.toml 's/^preferred_profile = "alpha"$/preferred_profile = "ghost"/')
assert_reject "preferred_profile must name a profile" "$F" "does not name a declared profile"
F=$(mut s-credboth.toml 's/^credential_mode = "claude-login"$/credential_mode = "claude-login"\ncredential_env = "A_KEY"/')
assert_reject "exactly one credential reference (both)" "$F" "exactly one of credential_mode | credential_env"
F=$(mut s-crednone.toml '/^credential_env = "CCT_LOCAL_API_KEY"$/d')
assert_reject "exactly one credential reference (none)" "$F" "exactly one of credential_mode | credential_env"
F=$(mut s-urlboth.toml 's|^base_url_env = "CCT_LOCAL_ANTHROPIC_BASE_URL"$|base_url_env = "CCT_LOCAL_ANTHROPIC_BASE_URL"\nbase_url = "http://127.0.0.1:8000"|')
assert_reject "at most one endpoint reference" "$F" "at most one of base_url | base_url_env"
F=$(mut s-credname.toml 's/^credential_env = "CCT_LOCAL_API_KEY"$/credential_env = "not-a-var-name"/')
assert_reject "credential_env must be an env-var NAME" "$F" "environment-variable NAME"
F=$(mut s-datapol.toml 's/^data_policy = "local-only"$/data_policy = "anywhere"/')
assert_reject "data_policy is closed" "$F" "data_policy 'anywhere' is not accepted"
F=$(mut s-backend.toml 's/^backend = "claude-code"$/backend = "cursor"/')
assert_reject "backend must be a known harness backend" "$F" "not a known harness backend"
F=$(mut s-boolen.toml 's/^enabled = true$/enabled = 1/')
assert_reject "policy.enabled must be boolean" "$F" "enabled must be a boolean"

assert_eq "unreadable file is exit 2 (usage, not violation)" "2" \
    "$( (rv "$TMP/absent.toml" >/dev/null 2>&1); echo $? )"

# ── SC-A3: credential hygiene ──
F=$(mut c-sk.toml 's/^model = "opus"$/model = "sk-abcdefghijklmnop"/')
assert_reject "defense in depth: sk- shaped value refused" "$F" "value-shaped secret"
F=$(mut c-bearer.toml 's/^tool_profile = "local-builder-minimal"$/tool_profile = "Bearer abc.def.ghi"/')
assert_reject "defense in depth: bearer token refused" "$F" "value-shaped secret"
F=$(mut c-hex.toml 's/^quota_pool = "local-vllm"$/quota_pool = "0123456789abcdef0123456789abcdef"/')
assert_reject "defense in depth: long hex run refused" "$F" "value-shaped secret"

# The STRUCTURAL boundary: with a sentinel value behind credential_env,
# no output of validate ever contains the value (nothing reads it).
export CCT_LOCAL_API_KEY="sentinel-secret-value-9f2c"
OUT=$(rv "$GOOD" 2>&1) || true
assert_eq "a set credential_env variable's VALUE never appears in output" "0" \
    "$(grep -c "sentinel-secret-value-9f2c" <<< "$OUT" || true)"
assert "…and the registry still validates with it set" rv "$GOOD"
unset CCT_LOCAL_API_KEY

echo ""
echo "========================================="
echo "  routing-config tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_CONFIG_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_CONFIG_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
