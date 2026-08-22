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
echo "=== T4: effective policy — the monotonic merge ==="
# effective_candidates(user, repo) SUBSET-OF candidates(user), with
# candidate identity = the COMPLETE EXECUTABLE TUPLE, never the id.
eff() { ( set +e; source "$LIB"; rc_effective "$1" "$2" ); }
wj() { printf '%s' "$2" > "$TMP/$1"; }

# candidates(user): every registry tuple, computed directly.
USER_TUPLES=$( ( source "$LIB"; rc_parse "$GOOD" || true
    i=0; while [[ $i -lt $RC_PROFILE_COUNT ]]; do rc_profile_tuple "$i"; i=$((i+1)); done ) )
assert_eq "the user candidate set carries 3 full tuples" "3" "$(grep -c '^\[' <<< "$USER_TUPLES")"
assert "tuples are canonical compact JSON (12 fields)" \
    jq -e -s 'length == 3 and (map(type == "array" and length == 12) | all)' <<< "$USER_TUPLES"
assert_eq "roles serialize as a SORTED set inside the tuple" '["build","land","reconcile"]' \
    "$(head -1 <<< "$USER_TUPLES" | jq -c '.[7]')"

# The generated matrix: (name, repo-doc-or--, want-enabled, want-count)
wj m-narrow.json '{"routing":{"allowed_profiles":["alpha"]}}'
wj m-repo-off.json '{"routing":{"enabled":false}}'
wj m-none.json '{}'
while IFS='|' read -r name repo wanten wantn; do
    [[ -z "$name" ]] && continue
    [[ "$repo" != "-" ]] && repo="$TMP/$repo"
    OUT=$(eff "$GOOD" "$repo") || true
    assert_eq "matrix/$name: enabled=$wanten, $wantn candidate(s)" "$wanten $wantn" \
        "$(jq -r '"\(.enabled) \(.candidates | length)"' <<< "$OUT")"
    # THE INVARIANT: every effective tuple is byte-identical to a user tuple.
    ok=true
    while IFS= read -r t; do
        [[ -z "$t" ]] && continue
        grep -qxF "$t" <<< "$USER_TUPLES" || ok=false
    done <<< "$(jq -c '.candidates[]' <<< "$OUT" 2>/dev/null)"
    assert_eq "matrix/$name: effective SUBSET-OF user (full-tuple equality)" "true" "$ok"
done <<'MATRIX'
repo-absent|-|true|3
no-routing-block|m-none.json|true|3
narrowing|m-narrow.json|true|1
repo-disable|m-repo-off.json|false|0
MATRIX
# (wj wrote into $TMP; eff needs full paths for the file cases)
OUT=$(eff "$GOOD" "$TMP/m-narrow.json")
assert_eq "narrowing keeps ONLY the allowed id" "alpha" "$(jq -r '.candidates[0][0]' <<< "$OUT")"
assert_eq "narrowing EXCLUDES the unlisted profiles" "0" "$(jq -c '.candidates[]' <<< "$OUT" | grep -c "alpha-opus" || true)"
assert_eq "the effective alpha tuple is BYTE-IDENTICAL to the registry's" \
    "$(head -1 <<< "$USER_TUPLES")" "$(jq -c '.candidates[0]' <<< "$OUT")"

# user-layer disable: both layers must agree to enable
U_OFF="$TMP/u-off.toml"; sed 's/^enabled = true$/enabled = false/' "$GOOD" > "$U_OFF"
assert_eq "user disable: enabled=false, EMPTY candidates" "false 0" \
    "$(eff "$U_OFF" "-" | jq -r '"\(.enabled) \(.candidates | length)"')"

# named cross-document violations
wj m-ghost.json '{"routing":{"allowed_profiles":["alpha","ghost"]}}'
OUT=$(eff "$GOOD" "$TMP/m-ghost.json") || true
assert "widening attempt: unknown repo id is a NAMED violation" \
    grep -q "names 'ghost', which the user registry does not define" <<< "$OUT"
wj m-badroute.json '{"routing":{"default_task_route":"warp_speed"}}'
OUT=$(eff "$GOOD" "$TMP/m-badroute.json") || true
assert "unknown default route class is a NAMED violation" \
    grep -q "names no route class in the user registry" <<< "$OUT"
wj m-route.json '{"routing":{"default_task_route":"tier1_only"}}'
assert_eq "a valid default route class is echoed" "tier1_only" \
    "$(eff "$GOOD" "$TMP/m-route.json" | jq -r '.default_task_route')"

# ADVERSARIAL IDENTITY: a repo that keeps a known id but tries to
# alter its resolved target cannot reach composition — the merge
# refuses any non-restriction key independently of the validator.
wj m-adversarial.json '{"routing":{"allowed_profiles":["alpha"],"profiles":[{"id":"alpha","model":"evil-model"}]}}'
RC=0
OUT=$(eff "$GOOD" "$TMP/m-adversarial.json") || RC=$?
assert_eq "adversarial: smuggled profile definitions refuse composition" "1" "${RC:-0}"
assert "adversarial: ...with the trust-boundary named" \
    grep -q "non-restriction key 'profiles'" <<< "$OUT"

# an invalid registry never composes
BADREG="$TMP/badreg.toml"; sed 's/^capability_tier = "tier2"$/capability_tier = "tier7"/' "$GOOD" > "$BADREG"
OUT=$(eff "$BADREG" "-") || true
assert "an invalid registry refuses composition" \
    grep -q "refusing to compose an effective policy over an invalid registry" <<< "$OUT"

# SEPARATOR-COLLISION regression: two structurally different
# candidates whose fields carry a would-be delimiter must NEVER
# serialize equal — canonical JSON, not naive joining.
# provider and model are ADJACENT tuple positions, so a naive join
# genuinely collides on this pair — that is what makes the regression
# discriminate against delimiter concatenation.
COLL="$TMP/coll.toml"
sed -e 's/^provider = "anthropic-subscription"$/provider = "anthropic|x"/' -e 's/^model = "sonnet"$/model = "y"/' "$GOOD" | head -63 > "$COLL"
COLL2="$TMP/coll2.toml"
sed -e 's/^provider = "anthropic-subscription"$/provider = "anthropic"/' -e 's/^model = "sonnet"$/model = "x|y"/' "$GOOD" | head -63 > "$COLL2"
TA=$( ( source "$LIB"; rc_parse "$COLL"  || true; rc_profile_tuple 0 ) )
TB=$( ( source "$LIB"; rc_parse "$COLL2" || true; rc_profile_tuple 0 ) )
assert "collision: separator-bearing fields stay structurally distinct" \
    test "$TA" != "$TB"
assert "collision: both remain valid JSON tuples" \
    jq -e -s 'map(type == "array") | all' <<< "$TA
$TB"
# roles are a SET: order in the registry does not change identity
RS1="$TMP/rs1.toml"; sed 's/^roles = \["build", "reconcile", "land"\]$/roles = ["land", "build", "reconcile"]/' "$GOOD" > "$RS1"
TR1=$( ( source "$LIB"; rc_parse "$GOOD" || true; rc_profile_tuple 0 ) )
TR2=$( ( source "$LIB"; rc_parse "$RS1"  || true; rc_profile_tuple 0 ) )
assert_eq "roles order carries no identity meaning (set semantics)" "$TR1" "$TR2"


echo ""
echo "=== T5: cct routing validate | status | explain ==="
CLI="$REPO_DIR/scripts/routing-cli.sh"
T5STATE="/nonexistent-state-t5"
cli() {  # <registry> <args...>
    ( set +e; CCT_ROUTING_REGISTRY="$1" CCT_ROUTING_STATE="$T5STATE" bash "$CLI" "${@:2}" 2>&1 )
}
rcof() { ( set +e; CCT_ROUTING_REGISTRY="$1" CCT_ROUTING_STATE="$T5STATE" bash "$CLI" "${@:2}" >/dev/null 2>&1 ); echo $?; }

# validate — validate only
OUT=$(cli "$GOOD" validate) || true
assert "validate: a valid registry is OK" grep -q "routing configuration OK" <<< "$OUT"
assert_eq "validate: no registry is exit 2 with guidance" "2" "$(rcof "$TMP/absent.toml" validate)"
assert "validate: ...naming non-configuration, not an error state" \
    grep -q "routing is not configured" <<< "$(cli "$TMP/absent.toml" validate)"
assert_eq "validate: an invalid registry is exit 1" "1" "$(rcof "$BADREG" validate)"
wj t5-repo-ok.json '{"schema_version":2,"profile":"advisory","routing":{"allowed_profiles":["alpha"]}}'
OUT=$(cli "$GOOD" validate --config "$TMP/t5-repo-ok.json") || true
assert "validate: registry + valid repo restrictions OK" grep -q "repo restrictions" <<< "$OUT"

# T3 PRECEDES T4: a config the standalone validator refuses never
# reaches composition — its cross-document symptom must be ABSENT.
wj t5-repo-bad.json '{"schema_version":2,"profile":"advisory","routing":{"tier2":{"x":1},"allowed_profiles":["ghost"]}}'
OUT=$(cli "$GOOD" validate --config "$TMP/t5-repo-bad.json") || true
assert "ordering: the T3 refusal surfaces" grep -q "owned by a later #109 increment" <<< "$OUT"
assert_eq "ordering: composition was NEVER reached (no cross-doc message)" "0" \
    "$(grep -c "does not define" <<< "$OUT" || true)"
wj t5-repo-ghost.json '{"schema_version":2,"profile":"advisory","routing":{"allowed_profiles":["ghost"]}}'
OUT=$(cli "$GOOD" validate --config "$TMP/t5-repo-ghost.json") || true
assert "validate: a T3-clean config still hits the T4 cross-doc violation" \
    grep -q "does not define" <<< "$OUT"

# status — registry/policy state only
OUT=$(cli "$GOOD" status) || true
assert "status: renders every profile row" \
    bash -c "grep -q '^alpha ' <<< '$OUT' && grep -q '^local-t2' <<< '$OUT'"
assert "status: absent state file is said plainly" grep -q "every profile is unknown" <<< "$OUT"
assert "status: unknown is the rendered state" grep -qE "alpha .*unknown" <<< "$OUT"
assert "status: the preferred profile is marked" grep -qE "alpha .*\*preferred" <<< "$OUT"
export CCT_LOCAL_API_KEY="sentinel-secret-value-9f2c"
OUT=$(cli "$GOOD" status) || true
assert "status: credential-env PRESENCE is reported" grep -q "env:CCT_LOCAL_API_KEY (set)" <<< "$OUT"
assert_eq "status: ...its VALUE never appears" "0" "$(grep -c "sentinel-secret-value-9f2c" <<< "$OUT" || true)"
unset CCT_LOCAL_API_KEY
OUT=$(cli "$GOOD" status) || true
assert "status: unset credential-env reported as unset" grep -q "env:CCT_LOCAL_API_KEY (unset)" <<< "$OUT"
printf '{"profiles":{"alpha":{"state":"cooldown"}}}\n' > "$TMP/t5-state.json"
OUT=$( ( set +e; CCT_ROUTING_REGISTRY="$GOOD" CCT_ROUTING_STATE="$TMP/t5-state.json" bash "$CLI" status 2>&1 ) )
assert "status: a recorded state renders (cooldown)" grep -qE "alpha .*cooldown" <<< "$OUT"
assert "status: unrecorded profiles stay unknown beside it" grep -qE "local-t2 .*unknown" <<< "$OUT"

# explain — pure configuration resolution
OUT=$(cli "$GOOD" explain --route-class tier1_only) || true
assert "explain: states it explains CONFIGURATION, not availability" \
    grep -q "not an availability decision" <<< "$OUT"
assert "explain: tier1_only rejects the tier2 profile BY TIER" \
    grep -q "local-t2: rejected — route class 'tier1_only' never reaches tier2" <<< "$OUT"
assert "explain: eligible rows carry tier + priority" \
    grep -q "alpha: eligible in tier1 at priority 10" <<< "$OUT"
assert_eq "explain: deterministic priority order within the tier" "alpha alpha-opus" \
    "$(grep -oE '^  (alpha|alpha-opus):' <<< "$OUT" | tr -d ' :' | tr '\n' ' ' | sed 's/ $//')"
assert "explain: unknown state is never treated as healthy" \
    grep -q "never treated as healthy" <<< "$OUT"
OUT=$(cli "$GOOD" explain --route-class tier2_fallback) || true
assert "explain: a fallback class reaches tier2" \
    grep -q "local-t2: eligible in tier2" <<< "$OUT"
OUT=$(cli "$GOOD" explain --route-class tier1_only --role reconcile) || true
assert "explain: role filtering is named" \
    grep -q "alpha-opus: rejected — does not hold role 'reconcile'" <<< "$OUT"
OUT=$(cli "$GOOD" explain --route-class tier1_only --config "$TMP/t5-repo-ok.json") || true
assert "explain: repository narrowing is named" \
    grep -q "alpha-opus: excluded by repository policy" <<< "$OUT"
OUT=$(cli "$U_OFF" explain --route-class tier1_only) || true
assert "explain: a disabled effective policy rejects everything" \
    grep -q "alpha: rejected — routing is disabled by the effective policy" <<< "$OUT"
assert_eq "explain: --route-class is required (usage exit)" "2" "$(rcof "$GOOD" explain)"
assert_eq "explain: an undeclared route class is a violation" "1" "$(rcof "$GOOD" explain --route-class warp)"

# PURITY: no network, no execution, no state writes — under a PATH
# shim where curl/wget/nc would loudly record any attempt.
SHIM="$TMP/shim"; mkdir -p "$SHIM"
for t in curl wget nc; do
    printf '#!/bin/sh\necho hit > "%s/net-marker"\nexit 7\n' "$TMP" > "$SHIM/$t"
    chmod +x "$SHIM/$t"
done
rm -f "$TMP/net-marker"
cp "$TMP/t5-state.json" "$TMP/t5-state.before"
( set +e
  PATH="$SHIM:$PATH" CCT_ROUTING_REGISTRY="$GOOD" CCT_ROUTING_STATE="$TMP/t5-state.json" \
    bash "$CLI" validate >/dev/null 2>&1
  PATH="$SHIM:$PATH" CCT_ROUTING_REGISTRY="$GOOD" CCT_ROUTING_STATE="$TMP/t5-state.json" \
    bash "$CLI" status >/dev/null 2>&1
  PATH="$SHIM:$PATH" CCT_ROUTING_REGISTRY="$GOOD" CCT_ROUTING_STATE="$TMP/t5-state.json" \
    bash "$CLI" explain --route-class tier2_fallback >/dev/null 2>&1 )
assert_eq "purity: no command touched the network (shim marker absent)" "no" \
    "$( [[ -e "$TMP/net-marker" ]] && echo yes || echo no )"
assert "purity: the state file is byte-identical after status+explain" \
    cmp -s "$TMP/t5-state.json" "$TMP/t5-state.before"

# the cct front door dispatches
assert "cct dispatch: cct routing status works end to end" \
    env CCT_ROUTING_REGISTRY="$GOOD" CCT_ROUTING_STATE="$T5STATE" bash "$REPO_DIR/scripts/cct" routing status

echo ""
echo "========================================="
echo "  routing-config tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_CONFIG_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_CONFIG_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
