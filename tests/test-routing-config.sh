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
echo "=== T2: normalized result — cause classification over the captured corpus ==="
RLIB="$REPO_DIR/scripts/lib/routing-result.sh"
FX="$SCRIPT_DIR/fixtures/routing"
SCHEMA="$REPO_DIR/shared/schemas/routing-result.schema.json"
# shellcheck source=/dev/null
source "$RLIB"

# Every captured fixture pins raw output -> exactly ONE cause. An HTTP
# status alone never determines cause (bare 403 -> unknown, the
# fail-closed residual); the dual-signal fixture pins the quota-before-
# rate precedence as INTENTIONAL.
cls_of() { rr_classify "$1" "$FX/$2" | jq -r '.failure_class // "null"'; }
while IFS='|' read -r fx rc want; do
    [[ -z "$fx" ]] && continue
    assert_eq "corpus: $fx -> $want" "$want" "$(cls_of "$rc" "$fx.out")"
done <<'CORPUS'
claude-session-limit|1|quota_exhausted
claude-weekly-limit|1|quota_exhausted
api-429-structured|1|rate_limited
api-429-text|1|rate_limited
api-auth-structured|1|auth
billing-text|1|auth
api-overloaded-structured|1|unavailable
http-503-text|1|unavailable
transport-refused|1|transport
transport-dns|1|transport
vllm-context-overflow|1|invalid_request
vllm-tool-shape|1|invalid_request
exec-tests-failed|1|execution
amb-403-quota|1|quota_exhausted
amb-403-cred|1|auth
amb-403-policy|1|denied
amb-403-bare|1|unknown
amb-dual-quota-rate|1|quota_exhausted
novel-unmatched|1|unknown
perm-error-bare|1|unknown
perm-error-policy|1|denied
success-clean|0|null
CORPUS

assert_eq "success outcome carries a null class" "success" \
    "$(rr_classify 0 "$FX/success-clean.out" | jq -r '.outcome')"
assert_eq "structured envelope: method structured, confidence high" "structured high" \
    "$(rr_classify 1 "$FX/api-429-structured.out" | jq -r '"\(.evidence.method) \(.evidence.confidence)"')"
assert_eq "text-only classification: method regex, confidence medium" "regex medium" \
    "$(rr_classify 1 "$FX/api-429-text.out" | jq -r '"\(.evidence.method) \(.evidence.confidence)"')"
assert_eq "regex evidence records the matching pattern" "true" \
    "$(rr_classify 1 "$FX/amb-403-quota.out" | jq '.evidence.pattern != null')"
assert_eq "unknown is low-confidence with NO pattern (a residual, not a match)" "regex low null" \
    "$(rr_classify 1 "$FX/novel-unmatched.out" | jq -r '"\(.evidence.method) \(.evidence.confidence) \(.evidence.pattern // "null")"')"
assert_eq "retry-after rides beside the class (structured)" "8" \
    "$(rr_classify 1 "$FX/api-429-structured.out" | jq -r '.retry_after_sec')"
assert_eq "retry-after rides beside the class (text)" "30" \
    "$(rr_classify 1 "$FX/api-429-text.out" | jq -r '.retry_after_sec')"
assert_eq "ISO reset time is extracted when present" "2026-08-24T10:00:00Z" \
    "$(rr_classify 1 "$FX/claude-weekly-limit.out" | jq -r '.reset_at')"

# The full composed document conforms to the CLOSED schema shape.
DOC=$(rr_result 1 "$FX/claude-session-limit.out" "claude-code" "anthropic-subscription" "alpha" "sonnet" "-" "anthropic-subscription" "api.anthropic.com" '{"stderr":"x.log"}')
assert_eq "rr_result: exact closed key set" \
    "artifacts backend effective_model evidence exit_code failure_class outcome profile provider quota_pool requested_model reset_at retry_after_sec schema_version upstream_origin" \
    "$(jq -r 'keys | sort | join(" ")' <<< "$DOC")"
assert_eq "rr_result: unverifiable effective model is null, never assumed" "null" \
    "$(jq -r '.effective_model // "null"' <<< "$DOC")"
assert_eq "rr_result: identity + pool are distinct fields" "claude-code anthropic-subscription alpha anthropic-subscription" \
    "$(jq -r '"\(.backend) \(.provider) \(.profile) \(.quota_pool)"' <<< "$DOC")"
assert_eq "rr_result: schema_version pinned" "1" "$(jq -r '.schema_version' <<< "$DOC")"
assert "rr_result: class enum member" \
    jq -e --arg c "$(jq -r '.failure_class' <<< "$DOC")" -n '["quota_exhausted","rate_limited","unavailable","transport","auth","invalid_request","denied","execution","unknown"] | index($c) != null'

# The schema artifact itself: parseable with a duplicate-key-rejecting
# parser, closed, and the frozen taxonomy pinned.
assert "schema: no duplicate keys (strict parse)" \
    python3 -c "
import json, sys
def no_dupes(pairs):
    ks=[k for k,_ in pairs]
    assert len(ks)==len(set(ks)), 'duplicate keys'
    return dict(pairs)
json.load(open('$SCHEMA'), object_pairs_hook=no_dupes)"
assert "schema: closed document" jq -e '.additionalProperties == false' "$SCHEMA"
assert_eq "schema: the frozen cause taxonomy, exactly" \
    "quota_exhausted rate_limited unavailable transport auth invalid_request denied execution unknown null" \
    "$(jq -r '.properties.failure_class.enum | map(. // "null") | join(" ")' "$SCHEMA")"
assert "schema: evidence object is closed" \
    jq -e '.properties.evidence.additionalProperties == false' "$SCHEMA"
assert "schema: success forces a null class" \
    jq -e '.allOf[0].then.properties.failure_class.const == null' "$SCHEMA"
assert "schema: failure forces a CLASSIFIED cause (never null)" \
    jq -e '.allOf[1].if.properties.outcome.const == "failure" and .allOf[1].then.properties.failure_class.type == "string"' "$SCHEMA"

# The boundary is BIDIRECTIONAL and executable: a success with a cause
# and a failure without one are both internally contradictory.
assert "invariant: the composed failure document conforms" rr_doc_invariant "$DOC"
assert "invariant: a success document conforms" \
    rr_doc_invariant "$(jq '.outcome = "success" | .failure_class = null' <<< "$DOC")"
assert_eq "invariant: success + a cause is REJECTED" "1" \
    "$( (rr_doc_invariant "$(jq '.outcome = "success"' <<< "$DOC")" >/dev/null 2>&1); echo $? )"
assert_eq "invariant: failure + null cause is REJECTED" "1" \
    "$( (rr_doc_invariant "$(jq '.failure_class = null' <<< "$DOC")" >/dev/null 2>&1); echo $? )"
assert_eq "invariant: failure + an invented cause is REJECTED" "1" \
    "$( (rr_doc_invariant "$(jq '.failure_class = "vibes"' <<< "$DOC")" >/dev/null 2>&1); echo $? )"

echo ""
echo "========================================="
echo "  routing-config tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_CONFIG_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_CONFIG_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
