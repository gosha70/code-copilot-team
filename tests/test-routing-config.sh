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
    "artifacts backend context_limit_declared context_limit_effective context_limit_evidence context_limit_observed effective_model evidence exit_code failure_class outcome profile provider quota_pool requested_model reset_at retry_after_sec schema_version upstream_origin" \
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
