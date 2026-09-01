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
F=$(mut s-failback.toml 's/^enabled = true$/enabled = true\nfailback = "auto"\nhealthy_probes_required = 3\nminimum_profile_dwell_sec = 45/')
assert "policy: the three recovery keys are promoted together" rv "$F"
F=$(mut s-polfuture2.toml 's/^enabled = true$/enabled = true\nmax_switches_per_task = 3/')
assert_reject "policy: max_switches_per_task stays refused" "$F" "not implemented by an owning increment"
F=$(mut s-badfailback.toml 's/^enabled = true$/enabled = true\nfailback = "next-task-boundary"/')
assert_reject "policy: failback has a closed auto|operator vocabulary" "$F" "failback must be 'auto' or 'operator'"
F=$(mut s-badthreshold.toml 's/^enabled = true$/enabled = true\nhealthy_probes_required = 0/')
assert_reject "policy: healthy_probes_required must be >= 1" "$F" "integer >= 1"
F=$(mut s-baddwell.toml 's/^enabled = true$/enabled = true\nminimum_profile_dwell_sec = -1/')
assert_reject "policy: minimum_profile_dwell_sec must be non-negative" "$F" "integer >= 0"
rc_parse "$GOOD" || true
assert_eq "policy: absent healthy threshold uses the named default" "2" "$(rc_healthy_probes_required)"
assert_eq "policy: absent dwell uses the named default" "300" "$(rc_minimum_profile_dwell_sec)"
assert_eq "policy: absent failback mode uses the named default" "auto" "$(rc_failback_policy)"
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
    "artifacts backend context_limit_declared context_limit_effective context_limit_evidence context_limit_observed effective_model evidence exit_code failure_class outcome profile provider quota_pool requested_model reset_at retry_after_sec schema_version upstream_origin usage" \
    "$(jq -r 'keys | sort | join(" ")' <<< "$DOC")"
assert_eq "rr_result: unverifiable effective model is null, never assumed" "null" \
    "$(jq -r '.effective_model // "null"' <<< "$DOC")"
assert_eq "rr_result: identity + pool are distinct fields" "claude-code anthropic-subscription alpha anthropic-subscription" \
    "$(jq -r '"\(.backend) \(.provider) \(.profile) \(.quota_pool)"' <<< "$DOC")"
assert_eq "rr_result: schema_version pinned" "1" "$(jq -r '.schema_version' <<< "$DOC")"
assert "rr_result: class enum member" \
    jq -e --arg c "$(jq -r '.failure_class' <<< "$DOC")" -n '["quota_exhausted","rate_limited","unavailable","transport","auth","invalid_request","denied","execution","unknown"] | index($c) != null'

# ── #109 increment F: context-limit recording ────────────────────────
# The numeric ceiling comes from the RECORDED capture, not a
# hand-written string: vllm-context-overflow.out states 32768.
assert_eq "F: the explicit numeric maximum is read from the recorded capture" "32768" \
    "$(rr_context_limit_observed "$FX/vllm-context-overflow.out" invalid_request)"
# Class-gated: the SAME bytes yield nothing when the class is not
# invalid_request. A number in an auth failure is not a context limit.
assert_eq "F: extraction is class-gated, not a free numeric scan" "" \
    "$(rr_context_limit_observed "$FX/vllm-context-overflow.out" auth)"
# Vague overflow: no number -> null, and today's behavior is untouched.
VAGUE="$TMP/f-vague.out"; printf 'Error: prompt is too long for this model.\n' > "$VAGUE"
assert_eq "F: vague overflow wording still classifies invalid_request" "invalid_request" \
    "$(rr_classify 1 "$VAGUE" | jq -r '.failure_class')"
assert_eq "F: ...but records NO observed limit" "" \
    "$(rr_context_limit_observed "$VAGUE" invalid_request)"

FDOC=$(rr_result 1 "$FX/vllm-context-overflow.out" claude-code local-vllm small qwen - poolF - '{}' 200000)
assert_eq "F: declared, observed and effective are recorded as three distinct facts" "200000 32768 32768" \
    "$(jq -r '"\(.context_limit_declared) \(.context_limit_observed) \(.context_limit_effective)"' <<< "$FDOC")"
assert_eq "F: the evidence source is named whenever a limit was observed" "invalid_request numeric maximum (this attempt)" \
    "$(jq -r '.context_limit_evidence' <<< "$FDOC")"
# THE CRUX (FR-F6): an observation is an upper bound seen while
# FAILING, never a capacity proof. With no declaration there is nothing
# to narrow, so effective stays null even though 32768 was observed.
FDOC_UNDECL=$(rr_result 1 "$FX/vllm-context-overflow.out" claude-code local-vllm small qwen - poolF - '{}' -)
assert_eq "F: an observation WITHOUT a declaration leaves effective null, never substituting for one" "null 32768 null" \
    "$(jq -r '"\(.context_limit_declared) \(.context_limit_observed) \(.context_limit_effective)"' <<< "$FDOC_UNDECL")"
# An observation ABOVE the declaration never broadens it.
FDOC_WIDE=$(rr_result 1 "$FX/vllm-context-overflow.out" claude-code local-vllm small qwen - poolF - '{}' 20000)
assert_eq "F: an observation above the declaration never broadens it" "20000" \
    "$(jq -r '.context_limit_effective' <<< "$FDOC_WIDE")"
# A clean success records the group as all-null, never a fabricated number.
FDOC_OK=$(rr_result 0 "$FX/success-clean.out" claude-code anthropic big sonnet - poolF - '{}' 200000)
assert_eq "F: a success observes nothing — no limit is ever fabricated" "null null" \
    "$(jq -r '"\(.context_limit_observed) \(.context_limit_evidence)"' <<< "$FDOC_OK")"

# Registry validation: positive integer, refused by name otherwise.
FBAD="$TMP/f-bad.toml"; sed 's/^priority = 10$/priority = 10\ncontext_limit = 0/' "$GOOD" > "$FBAD"
assert_eq "F: a non-positive context_limit is refused" "1" \
    "$( ( set +e; rc_validate "$FBAD" >/dev/null 2>&1; echo $? ) )"
assert "F: ...and the refusal says omission is the way to leave it undeclared" \
    grep -q "omit the key when the window is undeclared" <<< "$(rc_validate "$FBAD" 2>&1)"

# ── review round 2 ───────────────────────────────────────────────────
# MISLEADING NUMBERS must never become a durable cap. The loose
# pattern turned "error 42" into a 42-token ceiling, permanently
# stranding the profile; it also rejected legitimate small limits.
fx_num() { local f="$TMP/f-num.out"; printf '%s\n' "$1" > "$f"; rr_context_limit_observed "$f" invalid_request; }
assert_eq "F: an error CODE after the context phrase is not a limit" "" \
    "$(fx_num "maximum context length exceeded (error 42)")"
assert_eq "F: an HTTP code after the context phrase is not a limit" "" \
    "$(fx_num "maximum context window problem, code 503")"
assert_eq "F: a connector-form limit IS read" "32768" \
    "$(fx_num "maximum context length: 32768")"
assert_eq "F: 'context window of N' is read" "128000" \
    "$(fx_num "context window of 128000 tokens")"
assert_eq "F: a single-digit limit is valid and no longer excluded" "8" \
    "$(fx_num "maximum context length is 8 tokens")"

# PRIOR-OBSERVATION TELEMETRY. An attempt constrained by an earlier
# identity-bound observation that then SUCCEEDS must not report the
# declaration as effective — the record would contradict the routing
# decision it exists to explain.
FDOC_PRIOR=$(rr_result 0 "$FX/success-clean.out" claude-code local-vllm small qwen - poolF - '{}' 200000 32768)
assert_eq "F: a SUCCESS under a prior 32768 observation reports 32768 effective, not 200000" "200000 32768 32768" \
    "$(jq -r '"\(.context_limit_declared) \(.context_limit_observed) \(.context_limit_effective)"' <<< "$FDOC_PRIOR")"
assert_eq "F: ...and names the prior observation as the source" "prior identity-bound observation" \
    "$(jq -r '.context_limit_evidence' <<< "$FDOC_PRIOR")"
# This attempt's own overflow outranks a wider prior one.
FDOC_TIGHTER=$(rr_result 1 "$FX/vllm-context-overflow.out" claude-code local-vllm small qwen - poolF - '{}' 200000 65536)
assert_eq "F: this attempt's tighter overflow (32768) outranks a wider prior (65536)" "32768" \
    "$(jq -r '.context_limit_observed' <<< "$FDOC_TIGHTER")"
assert_eq "F: ...attributed to this attempt" "invalid_request numeric maximum (this attempt)" \
    "$(jq -r '.context_limit_evidence' <<< "$FDOC_TIGHTER")"

# NEW records must carry the complete, self-consistent group even
# though the schema keeps the fields optional for legacy compatibility.
assert "F: rr_doc_invariant accepts a complete new-form document" \
    rr_doc_invariant "$FDOC_PRIOR"
assert_eq "F: ...and REFUSES one missing the context group (legacy shape is not producible)" "1" \
    "$( ( set +e; rr_doc_invariant "$(jq -c 'del(.context_limit_declared,.context_limit_observed,.context_limit_effective,.context_limit_evidence)' <<< "$FDOC_PRIOR")"; echo $? ) )"
assert_eq "F: ...and REFUSES an effective limit that contradicts declared+observed" "1" \
    "$( ( set +e; rr_doc_invariant "$(jq -c '.context_limit_effective = 999999' <<< "$FDOC_PRIOR")"; echo $? ) )"
assert_eq "F: ...and REFUSES evidence without an observation" "1" \
    "$( ( set +e; rr_doc_invariant "$(jq -c '.context_limit_observed = null' <<< "$FDOC_PRIOR")"; echo $? ) )"

# ── SCHEMA-VERSION COMPATIBILITY, stated as behaviour ────────────────
# The decision (plan D6): schema_version stays 1 and the four
# context_limit_* fields stay OPTIONAL, so records written before F
# remain valid; completeness is enforced instead at the runtime
# boundary, which only ever sees documents F itself produced. The two
# halves are pinned together — either alone would be a silent trap.
LEGACY_DOC=$(jq -c 'del(.context_limit_declared,.context_limit_observed,.context_limit_effective,.context_limit_evidence)' <<< "$FDOC_PRIOR")
assert_eq "compat: schema_version is NOT bumped by the additive group" "1" \
    "$(jq -r '.properties.schema_version.const' "$SCHEMA")"
assert "compat: the four fields are absent from schema `required` (old records stay valid)" \
    jq -e '[.required[]] | any(startswith("context_limit")) | not' "$SCHEMA"
assert "compat: ...and the schema declares them, so new records are not additionalProperties violations" \
    jq -e '(.properties | has("context_limit_declared")) and (.properties | has("context_limit_effective"))' "$SCHEMA"
assert "compat: a pre-F record still VALIDATES against the shipped schema" \
    python3 -c "
import json,sys
sch=json.load(open('$SCHEMA')); doc=json.loads(sys.stdin.read())
req=set(sch['required']); missing=req-set(doc)
assert not missing, missing
allowed=set(sch['properties'])
assert set(doc)<=allowed, set(doc)-allowed
" <<< "$LEGACY_DOC"
assert_eq "compat: ...but a pre-F record can never be PRODUCED anew (runtime boundary refuses)" "1" \
    "$( ( set +e; rr_doc_invariant "$LEGACY_DOC"; echo $? ) )"
# The FOUR-CASE version matrix, so no reader ever best-guesses a shape
# it does not understand.
assert "compat/version: a current-version record is accepted" \
    rr_doc_invariant "$FDOC_PRIOR"
assert_eq "compat/version: an UNKNOWN FUTURE schema_version is REFUSED, never read as today's shape" "1" \
    "$( ( set +e; rr_doc_invariant "$(jq -c '.schema_version = 2' <<< "$FDOC_PRIOR")"; echo $? ) )"
assert_eq "compat/version: a missing schema_version is refused too" "1" \
    "$( ( set +e; rr_doc_invariant "$(jq -c 'del(.schema_version)' <<< "$FDOC_PRIOR")"; echo $? ) )"

# ── #109 increment G (#273): routed usage/cost evidence — C30 ────────
# Every assertion below is a counterexample to a REPRODUCED defect in
# the first implementation. Field presence proves nothing here: the
# first version had all the fields and still recorded forged evidence,
# zero-filled buckets, and prices from an unverified model.
gmk() { local f="$TMP/g-$1.out"; printf '%s\n' "$2" > "$f"; printf '%s' "$f"; }
gusage() { rr_result 0 "$1" "$2" openai gprofile REQ "$3" poolG - '{}' - - | jq -c '.usage'; }

# (1) PROVENANCE — usage is read only from a backend's authoritative
# result event. A non-authoritative event claiming tokens and USD must
# contribute NOTHING; the first version recorded 777/12 and $9.99 from
# a `type=assistant` line.
FORGED=$(gmk forged '{"type":"assistant","usage":{"input_tokens":777,"output_tokens":12},"total_cost_usd":9.99}')
assert_eq "G/provenance: a non-authoritative event contributes NO tokens" "null null unavailable" \
    "$(gusage "$FORGED" claude-code claude-sonnet-4-8 | jq -r '"\(.tokens.input) \(.tokens.output) \(.tokens.status)"')"
assert_eq "G/provenance: ...and no cost, however loudly it claims one" "null unavailable" \
    "$(gusage "$FORGED" claude-code claude-sonnet-4-8 | jq -r '"\(.cost.usd) \(.cost.basis)"')"
# An unknown backend has no authoritative event, so it reports nothing.
assert_eq "G/provenance: an unknown backend yields no usage rather than a guess" "unavailable" \
    "$(gusage "$(gmk auth '{"type":"result","usage":{"input_tokens":5},"total_cost_usd":1}')" mystery-backend claude-sonnet-4-8 | jq -r '.tokens.status')"

# (2) COMPLETE BUCKETS — a cost is computed only when every bucket with
# a non-zero rate is present. The first version zero-filled the rest,
# so an output-only transcript priced as if input were 0.
PARTIAL=$(gmk partial '{"type":"turn.completed","usage":{"output_tokens":30}}')
assert_eq "G/buckets: partial evidence does NOT produce a computed cost" "null unavailable" \
    "$(gusage "$PARTIAL" codex claude-sonnet-4-8 | jq -r '"\(.cost.usd) \(.cost.basis)"')"
assert_eq "G/buckets: ...while the partial token evidence is still retained" "30 reported" \
    "$(gusage "$PARTIAL" codex claude-sonnet-4-8 | jq -r '"\(.tokens.output) \(.tokens.status)"')"
FULL=$(gmk full '{"type":"turn.completed","usage":{"input_tokens":120,"output_tokens":30,"cached_input_tokens":50,"cache_creation_input_tokens":0}}')
assert_eq "G/buckets: complete buckets DO compute, with provenance" "computed 2026-05-01" \
    "$(gusage "$FULL" codex claude-sonnet-4-8 | jq -r '"\(.cost.basis) \(.cost.price_version)"')"
assert_eq "G/buckets: ...and the figure is derived from the observed tokens" "0.000825" \
    "$(gusage "$FULL" codex claude-sonnet-4-8 | jq -r '.cost.usd')"
assert_eq "G/buckets: an unreported bucket stays null, never zero-filled" "null" \
    "$(gusage "$PARTIAL" codex claude-sonnet-4-8 | jq -r '.tokens.input')"

# (3) VALIDATED PRICING — rates resolve through the existing config
# loader, so its documented DEEP-MERGE layering and its validation both
# apply. The first version picked the first file containing
# `pricing.models` and read it with raw jq: a partial override replaced
# the defaults, missing rates silently became 0, and the result was
# still labelled computed.
GPO="$TMP/g-price-partial.json"
printf '{"pricing":{"models":{"claude-sonnet-4-8":{"input":99.0}}}}\n' > "$GPO"
assert_eq "G/pricing: a partial override DEEP-MERGES over the defaults, never replacing them" "99.0 15.0 0.3" \
    "$( ( set +e; source "$REPO_DIR/scripts/lib/routing-usage.sh"
          ru_rate claude-sonnet-4-8 "$GPO" | jq -r '"\(.input) \(.output) \(.cache_read)"' ) )"
GPC="$TMP/g-price-currency.json"
printf '{"pricing":{"models":{"claude-sonnet-4-8":{"currency":"EUR","effective_date":"2026-09-01","input":2.5}}}}\n' > "$GPC"
assert_eq "G/pricing: a table mixing currencies is REFUSED, not silently priced" "" \
    "$( ( set +e; source "$REPO_DIR/scripts/lib/routing-usage.sh"
          ru_rate claude-sonnet-4-8 "$GPC" ) )"
assert "G/pricing: the shared validator names a missing rate rather than defaulting it to 0" \
    bash -c "PYTHONPATH='$REPO_DIR/scripts' python3 -c \"
from session_analytics.config import _load_pricing
try:
    _load_pricing({'pricing':{'models':{'m':{'currency':'USD','effective_date':'2026-09-01','input':2.5}}}})
    raise SystemExit(1)
except ValueError as e:
    raise SystemExit(0 if 'missing rate' in str(e) else 1)
\""
assert_eq "G/pricing: a verified model with no price entry is unpriced, never 0" "null unpriced" \
    "$(gusage "$FULL" codex totally-unpriced-model | jq -r '"\(.cost.usd) \(.cost.basis)"')"

# (4) VERIFIED IDENTITY — pricing uses the EFFECTIVE model only. The
# first version fell back to the requested model, contradicting the
# merged C13 finding that requested never proves served.
assert_eq "G/identity: an unverified effective model is never priced" "null unavailable" \
    "$(rr_result 0 "$FULL" codex openai gprofile claude-sonnet-4-8 - poolG - '{}' - - | jq -r '"\(.usage.cost.usd) \(.usage.cost.basis)"')"
assert_eq "G/identity: ...while a VERIFIED effective model prices normally" "computed" \
    "$(rr_result 0 "$FULL" codex openai gprofile REQ claude-sonnet-4-8 poolG - '{}' - - | jq -r '.usage.cost.basis')"

# (5) WRAPPER BOUNDARY — the supervisor's main path wraps the driver,
# whose stdout is a console log. Accounting-shaped log text must never
# become evidence; the driver publishes an aggregate instead.
LOG=$(gmk log '- Cost: metered $12.34, estimated $5.00 (cap $25)
[auto-build-loop.sh] input_tokens 999 output_tokens 888')
assert_eq "G/wrapper: accounting-shaped LOG TEXT is never read as evidence" "null unavailable null unavailable" \
    "$(gusage "$LOG" driver-aggregate claude-sonnet-4-8 | jq -r '"\(.tokens.input) \(.tokens.status) \(.cost.usd) \(.cost.basis)"')"
AGG=$(gmk agg '{"type":"cct.routed_usage","backend":"claude","input_tokens":120,"output_tokens":30,"cache_read_input_tokens":50,"cache_creation_input_tokens":0,"total_cost_usd":0.75}')
assert_eq "G/wrapper: the driver-published aggregate IS authoritative" "120 30 0.75 reported" \
    "$(gusage "$AGG" driver-aggregate claude-sonnet-4-8 | jq -r '"\(.tokens.input) \(.tokens.output) \(.cost.usd) \(.cost.basis)"')"
assert "G/wrapper: the supervisor joins that artifact instead of the console capture" \
    grep -q 'usage-\$attempt_no.jsonl" driver-aggregate' "$REPO_DIR/scripts/cooldown-supervisor.sh"
assert "G/wrapper: ...and the driver publishes it from ONE dispatch point" \
    grep -q 'publish_routed_usage "\${2:-}"' "$REPO_DIR/scripts/auto-build-loop.sh"
# BEHAVIOURAL, not structural: run the driver's publisher and read what
# it actually emits. The function is extracted so this exercises the
# real code without launching a build.
# Mirrors the driver's real startup: the supervisor EXPORTS the path,
# the driver captures it privately and unsets the exported variable
# before any backend runs. Running the publisher this way means the
# test exercises that contract rather than assuming it.
gpub() {  # <result-file-content> <backend> [second-content] -> emitted records
    ( set +e
      BACKEND="$2"
      SCRIPT_DIR="$REPO_DIR/scripts"
      err() { :; }
      export CCT_ROUTING_USAGE_OUT="$TMP/g-pub-$RANDOM.jsonl"
      ROUTED_USAGE_OUT="${CCT_ROUTING_USAGE_OUT:-}"; unset CCT_ROUTING_USAGE_OUT
      eval "$(sed -n '/^publish_routed_usage()/,/^}/p' "$REPO_DIR/scripts/auto-build-loop.sh")"
      local rf="$TMP/g-pub-in-$RANDOM.jsonl"; printf '%s\n' "$1" > "$rf"
      publish_routed_usage "$rf"
      if [[ -n "${3:-}" ]]; then
          local rf2="$TMP/g-pub-in2-$RANDOM.jsonl"; printf '%s\n' "$3" > "$rf2"
          publish_routed_usage "$rf2"
      fi
      [[ -f "$ROUTED_USAGE_OUT" ]] && cat "$ROUTED_USAGE_OUT" || true )
}
assert_eq "G/wrapper: the publisher emits a cct.routed_usage record from the result envelope" "cct.routed_usage 120 30 0.75" \
    "$(gpub '{"type":"result","total_cost_usd":0.75,"usage":{"input_tokens":120,"output_tokens":30}}' claude \
       | jq -r '"\(.type) \(.input_tokens) \(.output_tokens) \(.total_cost_usd)"')"
# EXPLICIT ABSENCE, not omission: a missing record would let a partial
# sum look like a complete run total.
assert_eq "G/wrapper: an invocation with no accounting still publishes an EXPLICIT absence record" "cct.routed_usage claude null null" \
    "$(gpub '{"type":"result","subtype":"success"}' claude \
       | jq -r '"\(.type) \(.backend) \(.input_tokens // "null") \(.total_cost_usd // "null")"')"
# PI: the authoritative event is `usage`, which a generic
# result/turn.completed selector silently dropped.
assert_eq "G/wrapper: pi token evidence is published (its authoritative event is `usage`)" "50 7 3" \
    "$(gpub '{"type":"usage","input_tokens":50,"output_tokens":7,"cache_read_tokens":3}
{"type":"result","total_cost_usd":0.33}' pi \
       | jq -r '"\(.input_tokens) \(.output_tokens) \(.cache_read_input_tokens)"')"
# MULTI-SESSION: two invocations must aggregate to the RUN total, not
# report only the last.
MULTI=$(gpub '{"type":"result","total_cost_usd":0.10,"usage":{"input_tokens":10,"output_tokens":2}}' claude \
              '{"type":"result","total_cost_usd":0.20,"usage":{"input_tokens":20,"output_tokens":3}}')
assert_eq "G/wrapper: two invocations publish two records" "2" "$(printf '%s\n' "$MULTI" | grep -c cct.routed_usage)"
assert_eq "G/wrapper: ...and the reader sums them into the RUN total, not the last session" "30 5 0.30000000000000004 reported" \
    "$( f="$TMP/g-multi.jsonl"; printf '%s\n' "$MULTI" > "$f"
        ( set +e; source "$REPO_DIR/scripts/lib/routing-usage.sh"
          ru_usage "$f" driver-aggregate claude-sonnet-4-8 \
            | jq -r '"\(.tokens.input) \(.tokens.output) \(.cost.usd) \(.cost.basis)"' ) )"
# CONSERVATIVE: one silent invocation makes the run total unknown
# rather than an understated partial sum.
MIXED=$(gpub '{"type":"result","total_cost_usd":0.10,"usage":{"input_tokens":10,"output_tokens":2}}' claude \
              '{"type":"result","subtype":"success"}')
assert_eq "G/wrapper: one invocation without accounting makes the run total UNKNOWN, not a partial sum" "null unavailable null unavailable" \
    "$( f="$TMP/g-mixed.jsonl"; printf '%s\n' "$MIXED" > "$f"
        ( set +e; source "$REPO_DIR/scripts/lib/routing-usage.sh"
          ru_usage "$f" driver-aggregate claude-sonnet-4-8 \
            | jq -r '"\(.tokens.input) \(.tokens.status) \(.cost.usd) \(.cost.basis)"' ) )"
assert_eq "G/wrapper: ...and its output is consumable end to end by the reader" "120 30 0.75 reported" \
    "$( f="$TMP/g-pub-rt.jsonl"
        gpub '{"type":"result","total_cost_usd":0.75,"usage":{"input_tokens":120,"output_tokens":30}}' claude > "$f"
        ( set +e; source "$REPO_DIR/scripts/lib/routing-usage.sh"
          ru_usage "$f" driver-aggregate claude-sonnet-4-8 \
            | jq -r '"\(.tokens.input) \(.tokens.output) \(.cost.usd) \(.cost.basis)"' ) )"

# STREAM SHAPES — the reader must accept every shape the shipped
# backend parser accepts. The first version split on newlines only, so
# an ordinary pretty-printed Claude result parsed as nothing.
PRETTY=$(gmk pretty '{
  "type": "result",
  "total_cost_usd": 0.75,
  "usage": { "input_tokens": 120, "output_tokens": 30 }
}')
assert_eq "G/shape: a PRETTY-PRINTED Claude result is parsed" "120 30 0.75 reported" \
    "$(gusage "$PRETTY" claude-code claude-sonnet-4-8 | jq -r '"\(.tokens.input) \(.tokens.output) \(.cost.usd) \(.cost.basis)"')"
ARR=$(gmk arr '[{"type":"result","total_cost_usd":0.5,"usage":{"input_tokens":10,"output_tokens":2}}]')
assert_eq "G/shape: a JSON ARRAY stream is parsed" "10 2 reported" \
    "$(gusage "$ARR" claude-code claude-sonnet-4-8 | jq -r '"\(.tokens.input) \(.tokens.output) \(.cost.basis)"')"
JL=$(gmk jl '{"type":"system"}
{"type":"result","total_cost_usd":0.25,"usage":{"input_tokens":7,"output_tokens":1}}')
assert_eq "G/shape: JSONL is still parsed, and only the authoritative line counts" "7 1 0.25" \
    "$(gusage "$JL" claude-code claude-sonnet-4-8 | jq -r '"\(.tokens.input) \(.tokens.output) \(.cost.usd)"')"

# CARDINALITY IS PER BACKEND: the driver aggregate sums every record,
# but a direct backend takes its LAST authoritative event, matching the
# shipped parsers. Summing two pi `usage` events would report 30/5
# where the pi parser keeps 20/3.
PI2=$(gmk pi2 '{"type":"usage","input_tokens":10,"output_tokens":2}
{"type":"usage","input_tokens":20,"output_tokens":3}')
assert_eq "G/cardinality: a direct pi capture takes the LAST usage event, never a sum" "20 3" \
    "$(gusage "$PI2" pi claude-sonnet-4-8 | jq -r '"\(.tokens.input) \(.tokens.output)"')"
# LEGACY untyped Claude result — explicitly supported by the shipped
# parser, and previously read as entirely unavailable.
LEG="$REPO_DIR/scripts/benchmark_runner/tests/fixtures/claude_code/transcript-openai-shape.json"
assert_eq "G/shape: the shipped LEGACY untyped Claude result is parsed" "9000 200 reported" \
    "$(gusage "$LEG" claude-code claude-sonnet-4-8 | jq -r '"\(.tokens.input) \(.tokens.output) \(.tokens.status)"')"
# ...but the fallback stays constrained: more than one event, or a
# typed non-authoritative event, must NOT readmit the forgery hole.
FORGE2=$(gmk forge2 '{"type":"assistant","usage":{"input_tokens":777}}
{"type":"other"}')
assert_eq "G/shape: the legacy fallback does not readmit forged multi-event streams" "unavailable" \
    "$(gusage "$FORGE2" claude-code claude-sonnet-4-8 | jq -r '.tokens.status')"

# DIAGNOSTIC TOLERANCE — direct claude and pi launches merge stderr
# into the same capture. One warning line must not erase valid usage;
# the shipped parsers skip unparseable lines, and so must this reader
# or the two disagree.
NOISY=$(gmk noisy 'warning: a diagnostic line on stderr
{"type":"usage","input_tokens":10,"output_tokens":2}
{"type":"usage","input_tokens":20,"output_tokens":3}')
assert_eq "G/shape: a stderr diagnostic does not erase valid usage" "20 3 reported" \
    "$(gusage "$NOISY" pi claude-sonnet-4-8 | jq -r '"\(.tokens.input) \(.tokens.output) \(.tokens.status)"')"
CLEAN=$(gmk clean2 '{"type":"usage","input_tokens":10,"output_tokens":2}
{"type":"usage","input_tokens":20,"output_tokens":3}')
assert_eq "G/shape: ...and matches the clean capture exactly" \
    "$(gusage "$CLEAN" pi claude-sonnet-4-8 | jq -c '.tokens')" \
    "$(gusage "$NOISY" pi claude-sonnet-4-8 | jq -c '.tokens')"
# Tolerance must not readmit forgery: skipping a bad line still leaves
# the authoritative-event requirement in force.
NOISYFORGE=$(gmk noisyforge 'warning: noise
{"type":"assistant","usage":{"input_tokens":777},"total_cost_usd":9.99}')
assert_eq "G/shape: skipping noise does not readmit a forged event" "unavailable" \
    "$(gusage "$NOISYFORGE" claude-code claude-sonnet-4-8 | jq -r '.tokens.status')"

# STREAM PROVENANCE — stdout only. Merged stderr let a VALID JSON
# diagnostic carrying an authoritative type impersonate the backend's
# own event and, as the last one, override real evidence. Skipping
# unparseable lines does not help: the forgery is well-formed JSON.
assert_eq "G/streams: usage is read from STDOUT, and the supervisor keeps them separate (codex+pi+claude, both sites)" "6" \
    "$(grep -c '2>"\$OUT.stderr"' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
# The load-bearing half: the USAGE argument must be stdout, not the
# combined view. Pinning only the classification argument left the
# actual forgery surface unguarded.
assert_eq "G/streams: the USAGE argument is stdout-only, never the combined view" "2" \
    "$(grep -c '"\$OUT" "\$(jq -r .\.backend. <<< "\$pj")")' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
assert_eq "G/streams: ...and the combined view is never passed as the usage source" "0" \
    "$(grep -c '"\$OUT.all" "\$(jq -r .\.backend. <<< "\$pj")")' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
assert_eq "G/streams: classification reads the COMBINED view, so no diagnostic is lost" "2" \
    "$(grep -c 'rr_result "\$CHILD_CODE" "\$OUT.all"' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
assert_eq "G/streams: the combined view is tracked for cleanup, never orphaned in /tmp" "2" \
    "$(grep -c 'rt_tmp_track "\$OUT" "\$OUT.stderr" "\$OUT.txt" "\$OUT.all"' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
# Behaviourally: a stdout-only capture is immune to the forgery that a
# merged capture accepts.
FORGED_MERGE=$(gmk forgedmerge '{"type":"usage","input_tokens":20,"output_tokens":3}
{"type":"usage","input_tokens":777,"output_tokens":12}')
assert_eq "G/streams: a merged stream WOULD be forgeable (why separation is required)" "777" \
    "$(gusage "$FORGED_MERGE" pi claude-sonnet-4-8 | jq -r '.tokens.input')"
STDOUT_ONLY=$(gmk stdoutonly '{"type":"usage","input_tokens":20,"output_tokens":3}')
assert_eq "G/streams: ...while the separated stdout carries only the backend's own event" "20 3" \
    "$(gusage "$STDOUT_ONLY" pi claude-sonnet-4-8 | jq -r '"\(.tokens.input) \(.tokens.output)"')"
# And the staged temp must be tracked the moment it exists.
assert_eq "G/staging: the staged file is tracked for cleanup immediately" "1" \
    "$(grep -c 'rt_tmp_track "\$RT_USAGE_TMP"' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
assert_eq "G/staging: a failed promotion is a NAMED accounting refusal, not a set -e exit" "1" \
    "$(grep -c 'could not be promoted to' "$REPO_DIR/scripts/cooldown-supervisor.sh")"

# CODEX STDERR MUST NOT REACH CLASSIFICATION. Separating the streams
# fixed usage provenance but reintroduced the #199 hazard through the
# combined classification view: codex echoes the prompt on stderr, so
# packet text could choose a failure class and therefore the routing
# action. BEHAVIOURAL counterfactual — the launch-redirection
# assertions cannot see a later concatenation.
CXO=$(gmk cx-stdout '{"type":"item.completed","item":{"text":"build failed somehow"}}')
CXE=$(gmk cx-both '{"type":"item.completed","item":{"text":"build failed somehow"}}
prompt echo: ... please handle the rate limit case ...')
assert_eq "G/codex: stdout alone classifies on its own evidence" "execution" \
    "$( ( set +e; source "$REPO_DIR/scripts/lib/routing-result.sh"; rr_classify 1 "$CXO" | jq -r '.failure_class' ) )"
assert_eq "G/codex: an echoed PROMPT on stderr would change the class (why it must be excluded)" "rate_limited" \
    "$( ( set +e; source "$REPO_DIR/scripts/lib/routing-result.sh"; rr_classify 1 "$CXE" | jq -r '.failure_class' ) )"
# ...so the supervisor must build the codex classification view from
# stdout ONLY, at both routed-backend sites.
assert_eq "G/codex: the classification view excludes codex stderr at both sites" "2" \
    "$(grep -c 'if \[\[ "\$(jq -r ..backend. <<< "\$pj")" != "codex" && -s "\$OUT.stderr" \]\]; then' \
        "$REPO_DIR/scripts/cooldown-supervisor.sh")"
assert_eq "G/codex: ...and no site appends codex stderr unconditionally" "0" \
    "$(grep -c '^ *\[\[ -s "\$OUT.stderr" \]\] && cat "\$OUT.stderr" >> "\$OUT.all"' \
        "$REPO_DIR/scripts/cooldown-supervisor.sh")"
# The legacy usage-pattern scan must read the SAME safe view, or real
# claude/pi stderr evidence is silently dropped.
assert_eq "G/codex: the legacy usage scan reads the safe classification view" "2" \
    "$(grep -c 'grep -iE "\$USAGE_PATTERN" "\$OUT.all"' "$REPO_DIR/scripts/cooldown-supervisor.sh")"

# ── #109 C30: the EFFECTIVE endpoint is recorded ─────────────────────
# The closure audit found `upstream_origin` null in every routed
# result: the reference was journaled, the endpoint never recorded. The
# distinction is the point — two profiles naming ONE variable can reach
# different servers.
RSO() { ( set +e
          eval "$(sed -n '/^rt_sanitize_origin()/,/^}/p' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
          rt_sanitize_origin "$1" ) }
assert_eq "C30/endpoint: a plain base URL records its origin" "https://api.anthropic.com" \
    "$(RSO 'https://api.anthropic.com')"
# CREDENTIALS and PATH must never become durable evidence.
assert_eq "C30/endpoint: credentials, path, query and fragment are stripped" "https://vllm.internal:8000" \
    "$(RSO 'https://user:s3cr3t@vllm.internal:8000/v1/chat?key=abc#f')"
assert_eq "C30/endpoint: ...so no secret survives into the origin" "" \
    "$( RSO 'https://user:s3cr3t@vllm.internal:8000/v1' | grep -o 's3cr3t' || true )"
assert_eq "C30/endpoint: an IPv6 literal with a port is preserved" "http://[::1]:8000" \
    "$(RSO 'http://[::1]:8000/v1')"
assert_eq "C30/endpoint: host case is normalized so one endpoint is not recorded as two" \
    "$(RSO 'https://api.example.com')" "$(RSO 'HTTPS://API.EXAMPLE.COM/x')"
# ABSENT or INVALID stays explicit — never the variable NAME, which
# would look like evidence while identifying nothing.
assert_eq "C30/endpoint: an unusable value is empty, never a substitute" "" "$(RSO 'not-a-url')"
assert_eq "C30/endpoint: the variable NAME is never recorded as an endpoint" "" "$(RSO 'CCT_LOCAL_URL')"
assert_eq "C30/endpoint: an empty resolution stays empty" "" "$(RSO '')"
assert_eq "C30/endpoint: a scheme with no authority is refused" "" "$(RSO 'https://')"

# THE FINDING ITSELF: one endpoint_ref, two resolved hosts, two
# distinguishable records.
assert_eq "C30/endpoint: two profiles sharing one endpoint_ref record DIFFERENT origins" "https://server-a:8000 https://server-b:8000" \
    "$( a=$(CCT_SHARED_URL='https://server-a:8000/v1' bash -c '
              eval "$(sed -n "/^rt_sanitize_origin()/,/^}/p" "'"$REPO_DIR"'/scripts/cooldown-supervisor.sh")"
              rt_sanitize_origin "$CCT_SHARED_URL"')
        b=$(CCT_SHARED_URL='https://server-b:8000/v1' bash -c '
              eval "$(sed -n "/^rt_sanitize_origin()/,/^}/p" "'"$REPO_DIR"'/scripts/cooldown-supervisor.sh")"
              rt_sanitize_origin "$CCT_SHARED_URL"')
        printf '%s %s' "$a" "$b" )"
# It must come from the RESOLVED value, not endpoint_ref.
assert "C30/endpoint: it is derived from the resolved base URL, not endpoint_ref" \
    grep -q 'RT_UPSTREAM_ORIGIN=$(rt_sanitize_origin "$RT_ENV_BASE_URL")' "$REPO_DIR/scripts/cooldown-supervisor.sh"
# ...and reaches the durable record at ALL THREE wiring sites.
assert_eq "C30/endpoint: all three rr_result sites carry the launch-bound origin" "3" \
    "$(grep -c '"\${RT_UPSTREAM_ORIGIN:--}"' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
assert_eq "C30/endpoint: no site still passes a bare - for the origin" "0" \
    "$(grep -c "<<< \"\$pj\")\" - '{}'" "$REPO_DIR/scripts/cooldown-supervisor.sh")"
# End to end: the value reaches upstream_origin in the durable result.
assert_eq "C30/endpoint: the durable result carries the sanitized origin" "https://vllm.internal:8000" \
    "$( ( set +e; source "$REPO_DIR/scripts/lib/routing-result.sh"
          rr_result 0 "$FULL" codex openai p REQ claude-sonnet-4-8 poolG \
            "$(RSO 'https://user:pw@vllm.internal:8000/v1')" '{}' - - \
            | jq -r '.upstream_origin' ) )"
assert_eq "C30/endpoint: an unknown endpoint stays null, not a placeholder" "null" \
    "$( ( set +e; source "$REPO_DIR/scripts/lib/routing-result.sh"
          rr_result 0 "$FULL" codex openai p REQ claude-sonnet-4-8 poolG - '{}' - - \
            | jq -r '.upstream_origin // "null"' ) )"

# RESOLVER FAILURE vs VALID-UNLISTED — a broken price table is an
# operator error and must never be recorded as `unpriced`, which
# asserts a valid table that simply lacks the model.
GBADCFG="$TMP/g-badcfg.json"
printf '{"pricing":{"models":{"claude-sonnet-4-8":{"currency":"EUR","effective_date":"2026-09-01","input":2.5}}}}\n' > "$GBADCFG"
assert_eq "G/resolver: a broken price table REFUSES (rc 3), never degrading to unpriced" "3" \
    "$( ( set +e; source "$REPO_DIR/scripts/lib/routing-usage.sh"
          ru_cost '{"input":1,"output":1,"cache_read":1,"cache_write":1,"status":"reported"}' \
            claude-sonnet-4-8 - "$GBADCFG" >/dev/null 2>&1; echo $? ) )"
assert_eq "G/resolver: a VALID table lacking the model is unpriced (rc 0)" "0 unpriced" \
    "$( ( set +e; source "$REPO_DIR/scripts/lib/routing-usage.sh"
          out=$(ru_cost '{"input":1,"output":1,"cache_read":1,"cache_write":1,"status":"reported"}' no-such-model - 2>/dev/null); rc=$?
          printf '%s %s' "$rc" "$(jq -r '.basis' <<< "$out")" ) )"
assert "G/resolver: a non-USD rate is refused rather than stored in a field named usd" \
    bash -c "cd '$REPO_DIR' && ! ( source scripts/lib/routing-usage.sh; ru_rate claude-sonnet-4-8 '$GBADCFG' ) >/dev/null 2>&1"

# EVIDENCE-CHANNEL STAGING — and its stated LIMIT. RT_DIR sits inside
# the backend's worktree and started-N.json reveals the attempt number,
# so a predictable `usage-N.jsonl` there was both discoverable and
# appendable while the child runs. Staging elsewhere and promoting
# after exit removes that. It does NOT make the channel safe from a
# hostile same-user child, which inherits TMPDIR — the assertions below
# are named for what they actually prove.
assert_eq "G/staging: the channel is staged outside the child worktree" "1" \
    "$(grep -c 'RT_USAGE_TMP="\$(mktemp)"' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
assert_eq "G/staging: the child is handed the staged path, never the durable one" "1" \
    "$(grep -c 'CCT_ROUTING_USAGE_OUT="\$RT_USAGE_TMP"' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
assert_eq "G/staging: the durable artifact is written only AFTER the child exits" "1" \
    "$(grep -c 'mv -f "\$RT_USAGE_TMP" "\$RT_DIR/usage-\$attempt_no.jsonl"' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
# WRITE ISOLATION, behaviourally: a record forged at the durable path
# BEFORE the run must not survive into the evidence, because promotion
# REPLACES rather than merges.
GISO="$TMP/g-iso"; mkdir -p "$GISO"
printf '{"type":"cct.routed_usage","backend":"claude","input_tokens":999999,"total_cost_usd":99.99}\n' \
    > "$GISO/usage-1.jsonl"
printf '{"type":"cct.routed_usage","backend":"claude","input_tokens":10,"output_tokens":2}\n' \
    > "$GISO/private.jsonl"
( set +e; mv -f "$GISO/private.jsonl" "$GISO/usage-1.jsonl" )   # the promotion step
assert_eq "G/staging: a record forged at the DURABLE path is REPLACED, never merged" "1 10" \
    "$(printf '%s %s' "$(grep -c cct.routed_usage "$GISO/usage-1.jsonl")" \
                      "$(jq -r '.input_tokens' < "$GISO/usage-1.jsonl")")"
assert_eq "G/staging: ...so that forged figure never reaches the reader" "10 2 reported" \
    "$( ( set +e; source "$REPO_DIR/scripts/lib/routing-usage.sh"
          ru_extract_tokens "$GISO/usage-1.jsonl" driver-aggregate \
            | jq -r '"\(.input) \(.output) \(.status)"' ) )"

# THE BOUNDARY IS PRODUCTION CODE, not a test-only predicate: rr_result
# must refuse to emit a document that violates it.
# The price override is an explicit ARGUMENT, never an ambient
# variable: production must not consult the process environment for it.
assert_eq "G/resolver: the override is a parameter, not an ambient env var" "0" \
    "$(grep -c 'RU_PRICE_OVERRIDE' "$REPO_DIR/scripts/lib/routing-usage.sh" "$REPO_DIR/scripts/lib/routing-result.sh" \
        | awk -F: '{n+=$2} END{print n+0}')"
# rr_result must REFUSE — not exit, not degrade — when usage cannot be
# resolved. Injected by stubbing the resolver, so this exercises
# rr_result's real propagation path.
assert_eq "G/boundary: rr_result REFUSES to emit when usage cannot be resolved" "1" \
    "$( ( set +e; source "$REPO_DIR/scripts/lib/routing-result.sh"
          ru_usage() { return 3; }
          rr_result 0 "$FULL" codex openai p REQ claude-sonnet-4-8 poolG - '{}' - - >/dev/null 2>&1
          echo $? ) )"
assert "G/boundary: ...naming unresolved usage evidence rather than failing silently" \
    bash -c "( set +e; source '$REPO_DIR/scripts/lib/routing-result.sh'
               ru_usage() { return 3; }
               rr_result 0 '$FULL' codex openai p REQ claude-sonnet-4-8 poolG - '{}' - - 2>&1 >/dev/null ) | grep -q 'usage evidence could not be resolved'"
# The supervisor must convert that refusal into a NAMED routing
# disposition, not an incidental set -e exit.
assert_eq "G/boundary: rr_result sites plus the promotion step route failure through the named refusal" "4" \
    "$(grep -c 'routing_usage_evidence_unresolved' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
assert "G/boundary: ...and that reason is a member of the CLOSED terminal enum" \
    bash -c "source '$REPO_DIR/scripts/lib/routing-actions.sh'; ra_terminal_valid routing_usage_evidence_unresolved"
assert "G/boundary: ...and the invariant is invoked by rr_result itself, not only by tests" \
    grep -q 'if ! rr_doc_invariant "\$doc"; then' "$REPO_DIR/scripts/lib/routing-result.sh"

# A backend-stated USD figure outranks computation.
REPORTED=$(gmk reported '{"type":"result","total_cost_usd":0.4213,"usage":{"input_tokens":9,"output_tokens":1}}')
assert_eq "G: a backend-stated USD figure outranks computation" "0.4213 reported" \
    "$(gusage "$REPORTED" claude-code claude-sonnet-4-8 | jq -r '"\(.cost.usd) \(.cost.basis)"')"
# The cost CAP is budget control, never observation.
assert_eq "G: a configured cost cap is NEVER read as usage evidence" "null unavailable" \
    "$( CAP_COST=25 CCT_COST_CAP_USD=25 bash -c '
          source "'"$REPO_DIR"'/scripts/lib/routing-usage.sh"
          jq -r "\"\(.cost.usd) \(.cost.basis)\"" <<< "$(ru_usage "'"$LOG"'" driver-aggregate claude-sonnet-4-8)"' )"

# (6) STRICT RUNTIME INVARIANT — the first version accepted a
# non-integer token value and a `reported` cost with a null figure.
GOOD_U=$(gusage "$FULL" codex claude-sonnet-4-8)
assert "G/invariant: a well-formed block is accepted" ru_doc_invariant "$GOOD_U"
gbad() { assert_eq "G/invariant: $1" "1" "$( ( set +e; ru_doc_invariant "$2"; echo $? ) )"; }
gbad "a non-integer token value is refused" \
    '{"tokens":{"input":"not-an-int","output":null,"cache_read":null,"cache_write":null,"status":"reported"},"cost":{"usd":null,"basis":"reported","price_version":null}}'
gbad "a reported cost with a null figure is refused" \
    '{"tokens":{"input":1,"output":1,"cache_read":null,"cache_write":null,"status":"reported"},"cost":{"usd":null,"basis":"reported","price_version":null}}'
gbad "status=reported with no values is refused (status must match evidence)" \
    '{"tokens":{"input":null,"output":null,"cache_read":null,"cache_write":null,"status":"reported"},"cost":{"usd":null,"basis":"unavailable","price_version":null}}'
gbad "a negative token count is refused" \
    '{"tokens":{"input":-5,"output":1,"cache_read":null,"cache_write":null,"status":"reported"},"cost":{"usd":null,"basis":"unavailable","price_version":null}}'
gbad "an unexpected key is refused" \
    '{"tokens":{"input":1,"output":1,"cache_read":null,"cache_write":null,"status":"reported"},"cost":{"usd":1,"basis":"reported","price_version":null},"extra":1}'
gbad "a computed cost without price_version is refused" \
    '{"tokens":{"input":1,"output":1,"cache_read":0,"cache_write":0,"status":"reported"},"cost":{"usd":0.5,"basis":"computed","price_version":null}}'
gbad "an unpriced cost carrying 0 instead of null is refused" \
    '{"tokens":{"input":1,"output":1,"cache_read":0,"cache_write":0,"status":"reported"},"cost":{"usd":0,"basis":"unpriced","price_version":null}}'

# Boundary + schema compatibility.
assert_eq "G: a record missing the usage block is refused by the boundary" "1" \
    "$( ( set +e; rr_doc_invariant "$(jq -c 'del(.usage)' <<< "$(rr_result 0 "$FULL" codex openai gprofile REQ claude-sonnet-4-8 poolG - '{}' - -)")"; echo $? ) )"
assert "G: schema keeps usage OPTIONAL so pre-G records stay valid" \
    jq -e '(.required | index("usage")) == null and (.properties | has("usage"))' "$SCHEMA"

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
assert "ordering: the T3 refusal surfaces (tier2 promoted with #254 T6 — its CLOSED block still refuses unknown keys)" grep -q "unknown key 'routing.tier2.x'" <<< "$OUT"
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
printf '{"schema_version":1,"profiles":{"alpha":{"state":"cooldown","next_probe_at":4102444800}},"pools":{},"applied":{}}\n' > "$TMP/t5-state.json"
OUT=$( ( set +e; CCT_ROUTING_REGISTRY="$GOOD" CCT_ROUTING_STATE="$TMP/t5-state.json" bash "$CLI" status 2>&1 ) )
assert "status: a recorded state renders (cooldown)" grep -qE "alpha .*cooldown" <<< "$OUT"
assert "status: the next probe instant is rendered beside the state" grep -q "4102444800" <<< "$OUT"
assert "status: unrecorded profiles stay unknown beside it" grep -qE "local-t2 .*unknown" <<< "$OUT"
printf '{"schema_version":1,"profiles":{"alpha":{"state":"cooldown","until":1,"next_probe_at":null}},"pools":{},"applied":{}}\n' > "$TMP/t5-state.json"
OUT=$( ( set +e; CCT_ROUTING_REGISTRY="$GOOD" CCT_ROUTING_STATE="$TMP/t5-state.json" bash "$CLI" status 2>&1 ) )
assert "status: renders effective expiry, not the stale stored state" grep -qE "alpha .*unknown" <<< "$OUT"
printf 'corrupt\n' > "$TMP/corrupt-routing-state.json"
assert "status: a present corrupt circuit store refuses instead of rendering unknown" \
    bash -c "! CCT_ROUTING_REGISTRY='$GOOD' CCT_ROUTING_STATE='$TMP/corrupt-routing-state.json' bash '$CLI' status >/dev/null 2>'$TMP/corrupt-status.err' && grep -q 'corrupt circuit state' '$TMP/corrupt-status.err'"

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
printf '{"schema_version":1,"profiles":{"alpha":{"state":"cooldown","until":4102444800}},"pools":{},"applied":{}}\n' > "$TMP/explain-state.json"
OUT=$( ( set +e; CCT_ROUTING_REGISTRY="$GOOD" CCT_ROUTING_STATE="$TMP/explain-state.json" \
    bash "$CLI" explain --route-class tier1_only 2>&1 ) )
assert "explain: renders the same effective circuit state as status" \
    grep -q "alpha: eligible.*state: cooldown" <<< "$OUT"
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

# The top-level help is the A5 surface a user actually reads, and it
# drifted once already: it advertised routing as "increment A —
# read-only" long after B-D shipped `enable` and `tick`, both of which
# MUTATE routing state. A help text that under-reports an impure
# command is a correctness defect, not cosmetics — pin every shipped
# subcommand AND the pure/impure split so the next increment cannot
# extend the surface without extending the help.
CCT_HELP="$(bash "$REPO_DIR/scripts/cct" help 2>&1)"
assert_eq "cct help: names every shipped routing subcommand, the task-addressed explain, and the impure split" "ok" \
    "$( _m=""
        for _s in validate status explain enable tick; do
            grep -qE "cct routing $_s\b" <<< "$CCT_HELP" || _m="$_m no-$_s"
        done
        grep -qE 'cct routing explain --feature <id> --task <id>' <<< "$CCT_HELP" || _m="$_m no-task-explain"
        grep -qiE 'impure' <<< "$CCT_HELP" || _m="$_m no-impure-label"
        grep -qiE 'increment A .*read-only' <<< "$CCT_HELP" && _m="$_m stale-read-only-claim"
        [[ -z "$_m" ]] && echo ok || echo "drift:$_m" )"

echo ""
echo "========================================="
echo "  routing-config tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_CONFIG_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_CONFIG_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
