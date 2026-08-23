#!/usr/bin/env bash
# test-routing-failover.sh — #251 (increment B of #109) T1: the
# circuit/quota-pool state store. Atomic, locked, idempotent,
# fail-closed, read-side decay, pool-outranks-profile.
#
# Run from the repo root: bash tests/test-routing-failover.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
SLIB="$REPO_DIR/scripts/lib/routing-state.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/cct-rfail.XXXXXX")"
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
# run a store operation in a fresh subshell against a given state file
S() {  # <state-file> <fn> [args...]
    ( set +e; CCT_ROUTING_STATE="$1" source "$SLIB"; "${@:2}" )
}

echo "=== routing-failover T1: the circuit state store (#251) ==="

ST="$TMP/state.json"

# ── absent vs corrupt vs foreign: fail-closed boundaries ──
assert_eq "an absent store reads as the empty skeleton" \
    '{"schema_version":1,"profiles":{},"pools":{},"applied":{}}' \
    "$(S "$ST" rs_read | jq -c .)"
assert_eq "absent store: effective state is unknown" "unknown" \
    "$(S "$ST" rs_effective_state alpha poolA)"
printf '{"schema_version":1,"profiles":{' > "$TMP/corrupt.json"
assert_eq "a CORRUPT store is refused (exit 2), never treated as empty" "2" \
    "$( (S "$TMP/corrupt.json" rs_read >/dev/null 2>&1); echo $? )"
OUT=$(S "$TMP/corrupt.json" rs_read 2>&1) || true
assert "corrupt refusal names the boundary" \
    grep -q "refusing to act on corrupt circuit state" <<< "$OUT"
printf '{"schema_version":2,"profiles":{},"pools":{},"applied":{}}\n' > "$TMP/foreign.json"
assert_eq "a foreign schema_version is refused (exit 2)" "2" \
    "$( (S "$TMP/foreign.json" rs_read >/dev/null 2>&1); echo $? )"
printf '{"schema_version":1,"profiles":{}}\n' > "$TMP/partial.json"
assert_eq "a PARTIAL shape is refused (exit 2)" "2" \
    "$( (S "$TMP/partial.json" rs_read >/dev/null 2>&1); echo $? )"
assert_eq "rs_apply over a corrupt store refuses and writes NOTHING" "2" \
    "$( (S "$TMP/corrupt.json" rs_set_profile a1 alpha cooldown test - >/dev/null 2>&1); echo $? )"
assert_eq "…the corrupt file is untouched" '{"schema_version":1,"profiles":{' \
    "$(cat "$TMP/corrupt.json")"

# ── basic mutation + persistence ──
S "$ST" rs_set_profile at-1 alpha cooldown "rate limited" "$(( $(date -u +%s) + 3600 ))" >/dev/null 2>&1
assert_eq "a profile mutation persists" "cooldown" "$(jq -r '.profiles.alpha.state' "$ST")"
assert_eq "…and reads back as the effective state (until in the future)" "cooldown" \
    "$(S "$ST" rs_effective_state alpha poolA)"
assert_eq "…the applied set records the attempt id" "true" "$(jq '.applied | has("at-1")' "$ST")"

# ── idempotency (decision 5 step 4) ──
S "$ST" rs_set_profile at-1 alpha disabled "SHOULD NOT APPLY" - >/dev/null 2>&1
assert_eq "replaying the SAME attempt id is a no-op (state unchanged)" "cooldown" \
    "$(jq -r '.profiles.alpha.state' "$ST")"
OUT=$(S "$ST" rs_set_profile at-1 alpha disabled "x" - 2>&1) || true
assert "…and the no-op is journaled" grep -q "idempotent no-op" <<< "$OUT"
S "$ST" rs_set_profile at-2 alpha disabled "auth failure" - >/dev/null 2>&1
assert_eq "a NEW attempt id applies normally" "disabled" "$(jq -r '.profiles.alpha.state' "$ST")"

# ── decay: time-based, to unknown, never healthy; disabled never decays ──
S "$ST" rs_set_profile at-3 beta cooldown "throttled" "$(( $(date -u +%s) - 10 ))" >/dev/null 2>&1
assert_eq "a passed until decays to UNKNOWN (never healthy)" "unknown" \
    "$(S "$ST" rs_effective_state beta poolB)"
assert_eq "disabled (auth) has no until and NEVER decays" "disabled" \
    "$(S "$ST" rs_effective_state alpha poolA)"
S "$ST" rs_mark_success at-4 gamma >/dev/null 2>&1
assert_eq "an explicit success marks healthy (the only healthy source in B)" "healthy" \
    "$(S "$ST" rs_effective_state gamma poolC)"

# ── pool outranks profile ──
S "$ST" rs_set_pool at-5 poolC cooldown "subscription exhausted" "$(( $(date -u +%s) + 3600 ))" >/dev/null 2>&1
assert_eq "a blocked pool OUTRANKS a healthy member profile" "pool:cooldown" \
    "$(S "$ST" rs_effective_state gamma poolC)"
S "$ST" rs_set_pool at-6 poolD cooldown "exhausted" "$(( $(date -u +%s) - 5 ))" >/dev/null 2>&1
assert_eq "a DECAYED pool block falls through to the profile state" "healthy" \
    "$(S "$ST" rs_effective_state gamma poolD)"

# ── failed mutation writes nothing ──
BEFORE=$(cat "$ST")
S "$ST" rs_apply at-7 '.profiles[$p] = (1/0)' --arg p x >/dev/null 2>&1 || true
assert_eq "a failed jq mutation leaves the store byte-identical" "$BEFORE" "$(cat "$ST")"

# ── idempotency has NO horizon (decision 5: crash contract, not cache) ──
HZ="$TMP/horizon.json"
S "$HZ" rs_set_profile early alpha cooldown "first action" - >/dev/null 2>&1
i=0
while [[ $i -lt 55 ]]; do
    S "$HZ" rs_apply "bulk-$i" '.' >/dev/null 2>&1
    i=$((i+1))
done
assert_eq "55 later attempts never evict an applied id" "true" "$(jq '.applied | has("early")' "$HZ")"
OUT=$(S "$HZ" rs_set_profile early alpha disabled "MUST NOT REAPPLY" - 2>&1) || true
assert "replaying an attempt beyond 50 newer ones is STILL a no-op" \
    grep -q "idempotent no-op" <<< "$OUT"
assert_eq "…and the state is unchanged" "cooldown" "$(jq -r '.profiles.alpha.state' "$HZ")"

# ── atomicity under concurrency: a reader NEVER sees a torn document ──
CC="$TMP/conc.json"
S "$CC" rs_apply seed '.' >/dev/null 2>&1
( i=0; while [[ $i -lt 20 ]]; do
    S "$CC" rs_set_profile "cc-$i" "p$i" cooldown "load test padding padding padding padding padding" - >/dev/null 2>&1
    i=$((i+1))
  done ) &
WPID=$!
TORN=0; READS=0
while kill -0 "$WPID" 2>/dev/null; do
    if [[ -e "$CC" ]]; then
        READS=$((READS+1))
        jq -e '.schema_version == 1' "$CC" >/dev/null 2>&1 || TORN=$((TORN+1))
    fi
done
wait "$WPID" 2>/dev/null || true
assert_eq "concurrent reader observed ZERO torn documents (reads: $READS)" "0" "$TORN"
assert_eq "…and every writer landed exactly once" "20" "$(jq '[.profiles | keys[] | select(startswith("p"))] | length' "$CC")"

# ── lock: owner-aware takeover matrix ──
# dead owner + threshold -> loud takeover
LK="$TMP/locky.json"
mkdir -p "$LK.lock"
( : ) & DEAD=$!; wait "$DEAD" 2>/dev/null || true
echo "$DEAD" > "$LK.lock/pid"
OUT=$(CCT_ROUTING_LOCK_STALE_SEC=1 bash -c "sleep 2; set +e; CCT_ROUTING_STATE='$LK' source '$SLIB'; rs_set_profile lk-1 alpha cooldown x - " 2>&1) || true
assert "threshold + CONFIRMED-DEAD owner: loud takeover" grep -q "lock_takeover" <<< "$OUT"
assert "…naming the dead owner pid" grep -q "CONFIRMED-DEAD owner pid $DEAD" <<< "$OUT"
assert_eq "…and the mutation then applies" "cooldown" "$(jq -r '.profiles.alpha.state' "$LK")"

# live owner + threshold -> NEVER stolen (safety over liveness)
LV="$TMP/livelock.json"
mkdir -p "$LV.lock"
sleep 30 & LIVE=$!
echo "$LIVE" > "$LV.lock/pid"
RC=0
OUT=$(CCT_ROUTING_LOCK_STALE_SEC=1 bash -c "sleep 2; set +e; CCT_ROUTING_STATE='$LV' source '$SLIB'; rs_set_profile lv-1 alpha cooldown x - " 2>&1) || RC=$?
assert "threshold + LIVE owner: the lock is NOT stolen" grep -q "lock_busy_live_owner" <<< "$OUT"
assert_eq "…the writer fails busy instead (exit 2)" "2" "$RC"
assert_eq "…no mutation was applied" "no" "$( [[ -e "$LV" ]] && echo yes || echo no )"
assert_eq "…and the live owner's lock survives" "$LIVE" "$(cat "$LV.lock/pid")"
kill "$LIVE" 2>/dev/null || true

# unverifiable owner + threshold -> FAIL CLOSED, no takeover
UV="$TMP/unver.json"
mkdir -p "$UV.lock"   # no pid file at all
RC=0
OUT=$(CCT_ROUTING_LOCK_STALE_SEC=1 bash -c "sleep 2; set +e; CCT_ROUTING_STATE='$UV' source '$SLIB'; rs_set_profile uv-1 alpha cooldown x - " 2>&1) || RC=$?
assert "threshold + UNVERIFIABLE owner: refused with guidance" \
    grep -q "owner is unverifiable" <<< "$OUT"
assert_eq "…fail closed (exit 2), lock intact" "2" "$RC"
assert_eq "…no state file was created" "no" "$( [[ -e "$UV" ]] && echo yes || echo no )"

# unlock is owner-aware: a foreign process cannot remove a replacement lock
FO="$TMP/foreignlock.json"
S "$FO" rs_apply fo-1 '.' >/dev/null 2>&1
mkdir -p "$FO.lock"; echo "999999" > "$FO.lock/pid"
( set +e; CCT_ROUTING_STATE="$FO" source "$SLIB"; rs_unlock ) >/dev/null 2>&1
assert_eq "owner-aware unlock: a non-owner cannot remove the lock" "999999" \
    "$(cat "$FO.lock/pid" 2>/dev/null)"


echo ""
echo "=== T2: class->action — the total table, executable ==="
ALIB="$REPO_DIR/scripts/lib/routing-actions.sh"
RLIB="$REPO_DIR/scripts/lib/routing-result.sh"
FX="$SCRIPT_DIR/fixtures/routing"
# shellcheck source=/dev/null
source "$ALIB"
# a decision from a REAL corpus fixture, through A's own composer
res() {  # <fixture> <exit> -> normalized result json
    ( set +e; source "$RLIB"; rr_result "$2" "$FX/$1" claude-code anthropic-subscription alpha sonnet - poolA - '{}' )
}
T0=1787400000   # the durable decision epoch: every deadline derives from THIS
dec() { ra_decide "$1" "${2:-0}" "$T0"; }

# success -> proceed
D=$(dec "$(res success-clean.out 0)")
assert_eq "success -> proceed, no state op" "proceed none" "$(jq -r '"\(.action) \(.state_op.kind)"' <<< "$D")"

# quota WITH provider reset evidence -> pool cooldown to that instant
D=$(dec "$(res claude-weekly-limit.out 1)")
assert_eq "quota+reset: failover with POOL cooldown" "failover pool_cooldown" "$(jq -r '"\(.action) \(.state_op.kind)"' <<< "$D")"
assert_eq "quota+reset: until == the provider reset instant" \
    "$(date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "2026-08-24T10:00:00Z" +%s 2>/dev/null || date -u -d "2026-08-24T10:00:00Z" +%s)" \
    "$(jq -r '.state_op.until' <<< "$D")"
assert_eq "quota: terminal reason from the closed enum" "routing_pool_exhausted" "$(jq -r '.terminal_reason' <<< "$D")"

# quota WITHOUT usable reset evidence -> bounded fallback FROM THE
# DURABLE EPOCH, exactly (never the wall clock)
D=$(dec "$(res claude-session-limit.out 1)")
assert_eq "quota w/o reset: bounded fallback from the durable epoch, EXACT" \
    "$((T0 + 3600))" "$(jq -r '.state_op.until' <<< "$D")"
assert "quota w/o reset: the fallback is journaled BY NAME" \
    grep -q "bounded fallback cooldown (RA_QUOTA_FALLBACK_COOLDOWN_SEC=3600s)" <<< "$(jq -r '.journal' <<< "$D")"

# rate_limited: exactly ONE same-profile retry, deadlines ABSOLUTE
D=$(dec "$(res api-429-text.out 1)" 0)
assert_eq "rate first occurrence: retry SAME profile, Retry-After honored (absolute)" "retry_same $((T0 + 30)) none" \
    "$(jq -r '"\(.action) \(.retry_not_before) \(.state_op.kind)"' <<< "$D")"
D=$(dec "$(res api-429-structured.out 1)" 0)
assert_eq "rate first occurrence (structured): retry-after 8 honored" "$((T0 + 8))" "$(jq -r '.retry_not_before' <<< "$D")"
NORA=$(res api-429-text.out 1 | jq '.retry_after_sec = null')
D=$(dec "$NORA" 0)
assert_eq "rate without retry-after: the named default delay" "$((T0 + 60))" "$(jq -r '.retry_not_before' <<< "$D")"
D=$(dec "$(res api-429-text.out 1)" 1)
assert_eq "rate PAST the single-retry budget: failover + profile cooldown" "failover profile_cooldown routing_rate_limited" \
    "$(jq -r '"\(.action) \(.state_op.kind) \(.terminal_reason)"' <<< "$D")"

# unavailable / transport: one retry then circuit-open
D=$(dec "$(res api-overloaded-structured.out 1)" 0)
assert_eq "unavailable first: one retry after the named default" "retry_same $((T0 + 30))" "$(jq -r '"\(.action) \(.retry_not_before)"' <<< "$D")"
D=$(dec "$(res api-overloaded-structured.out 1)" 1)
assert_eq "unavailable past budget: profile cooldown + enum reason" "failover profile_cooldown routing_provider_unavailable" \
    "$(jq -r '"\(.action) \(.state_op.kind) \(.terminal_reason)"' <<< "$D")"
D=$(dec "$(res transport-refused.out 1)" 1)
assert_eq "transport past budget: its own enum reason" "routing_transport_failure" "$(jq -r '.terminal_reason' <<< "$D")"

# auth: disable exactly that profile, keep going
D=$(dec "$(res api-auth-structured.out 1)")
assert_eq "auth: profile DISABLED (no until), failover continues" "failover profile_disable null" \
    "$(jq -r '"\(.action) \(.state_op.kind) \(.state_op.until)"' <<< "$D")"

# invalid_request: attempt-local, zero durable state
D=$(dec "$(res vllm-context-overflow.out 1)")
assert_eq "invalid_request: attempt-local incompatibility, NO state op" "failover none true routing_task_incompatible" \
    "$(jq -r '"\(.action) \(.state_op.kind) \(.attempt_local_incompatible) \(.terminal_reason)"' <<< "$D")"

# denied / unknown: fail closed, never rerouted
D=$(dec "$(res amb-403-policy.out 1)")
assert_eq "denied: park, never rerouted around" "park routing_policy_denied" "$(jq -r '"\(.action) \(.terminal_reason)"' <<< "$D")"
D=$(dec "$(res exec-tests-failed.out 1)")
assert_eq "execution: the breaker path, no router action" "breaker none null" \
    "$(jq -r '"\(.action) \(.state_op.kind) \(.terminal_reason)"' <<< "$D")"
D=$(dec "$(res novel-unmatched.out 1)")
assert_eq "unknown: park, fail closed" "park routing_unknown_failure" "$(jq -r '"\(.action) \(.terminal_reason)"' <<< "$D")"
FORGED=$(res novel-unmatched.out 1 | jq '.failure_class = "vibes"')
D=$(dec "$FORGED")
assert_eq "an unlisted cause (frozen-taxonomy violation) fails closed like unknown" "park routing_unknown_failure" \
    "$(jq -r '"\(.action) \(.terminal_reason)"' <<< "$D")"

# the closed enum is the ONLY reason source
assert "the enum guard rejects a non-member" \
    bash -c "source '$ALIB'; ! ra_terminal_valid routing_made_up"
assert "routing_attempt_indeterminate and no_eligible_profile are distinct members" \
    bash -c "source '$ALIB'; ra_terminal_valid routing_attempt_indeterminate && ra_terminal_valid routing_no_eligible_profile"
ALL_OK=true
for fx in claude-weekly-limit:1 api-429-text:1 api-overloaded-structured:1 transport-refused:1 api-auth-structured:1 vllm-context-overflow:1 amb-403-policy:1 novel-unmatched:1; do
    T=$(dec "$(res "${fx%%:*}.out" "${fx##*:}")" 1 | jq -r '.terminal_reason // empty')
    if [[ -n "$T" ]]; then
        ( source "$ALIB"; ra_terminal_valid "$T" ) || ALL_OK=false
    fi
done
assert_eq "every emitted terminal reason is an enum member" "true" "$ALL_OK"

# REPLAY DETERMINISM: the decision is a pure function of
# (result, retries, decision_epoch) — recomputation after wall time
# has advanced yields BYTE-IDENTICAL deadlines.
RES_Q=$(res claude-session-limit.out 1)
D1=$(dec "$RES_Q")
sleep 1.1
D2=$(dec "$RES_Q")
assert_eq "replay: byte-identical decision after wall time advanced" "$D1" "$D2"
RES_R=$(res api-429-text.out 1)
R1=$(dec "$RES_R" 0); R2=$(dec "$RES_R" 0)
assert_eq "replay: retry deadline is epoch-anchored, not clock-anchored" \
    "$(jq -r '.retry_not_before' <<< "$R1")" "$(jq -r '.retry_not_before' <<< "$R2")"
RCE=0
OUT=$(ra_decide "$RES_Q" 0 2>&1) || RCE=$?
assert_eq "a missing decision epoch is REFUSED (never wall-clock substituted)" "1" "$RCE"
assert "…naming the temporal-basis rule" grep -q "wall clock never substitutes" <<< "$OUT"

# ISO helper boundaries
assert_eq "iso helper: Z timestamp parses" "yes" \
    "$( ( source "$ALIB"; ra_iso_to_epoch 2026-08-24T10:00:00Z >/dev/null ) && echo yes )"
assert_eq "iso helper: garbage fails (rc 1), never invents an epoch" "no" \
    "$( ( source "$ALIB"; ra_iso_to_epoch "resets at 3am" >/dev/null 2>&1 ) && echo yes || echo no )"


echo ""
echo "=== T3: deterministic tier1 selection ==="
CLIB="$REPO_DIR/scripts/lib/routing-config.sh"
REG="$TMP/sel-reg.toml"
cat > "$REG" <<'REOF'
schema_version = 1

[policy]
enabled = true

[route_classes.tier1_only]
tier_order = ["tier1"]

[[profiles]]
id = "alpha"
backend = "claude-code"
provider = "anthropic-subscription"
model = "sonnet"
capability_tier = "tier1"
priority = 10
quota_pool = "poolA"
roles = ["build", "reconcile"]
tool_profile = "full-cct"
credential_mode = "claude-login"
data_policy = "approved-cloud"

[[profiles]]
id = "beta"
backend = "claude-code"
provider = "deepseek-api"
model = "deepseek-v4"
capability_tier = "tier1"
priority = 20
quota_pool = "poolB"
roles = ["build"]
tool_profile = "deepseek-compatible"
credential_env = "DEEPSEEK_API_KEY"
data_policy = "approved-cloud"

[[profiles]]
id = "delta"
backend = "pi"
provider = "anthropic-subscription"
model = "sonnet"
capability_tier = "tier1"
priority = 30
quota_pool = "poolA"
roles = ["build"]
tool_profile = "full-cct"
credential_mode = "claude-login"
data_policy = "approved-cloud"

[[profiles]]
id = "rho"
backend = "claude-code"
provider = "openai"
model = "gpt"
capability_tier = "tier1"
priority = 40
quota_pool = "poolD"
roles = ["reconcile"]
tool_profile = "full-cct"
credential_env = "OPENAI_API_KEY"
data_policy = "approved-cloud"

[[profiles]]
id = "sigma"
backend = "claude-code"
provider = "local-vllm"
model = "qwen-big"
capability_tier = "tier2"
priority = 5
quota_pool = "poolC"
roles = ["build"]
tool_profile = "local-builder-minimal"
credential_env = "CCT_LOCAL_API_KEY"
data_policy = "local-only"

[[profiles]]
id = "gamma"
backend = "claude-code"
provider = "local-vllm"
model = "qwen"
capability_tier = "tier2"
priority = 10
quota_pool = "poolC"
roles = ["bounded-build"]
tool_profile = "local-builder-minimal"
credential_env = "CCT_LOCAL_API_KEY"
data_policy = "local-only"
REOF
EFF=$( ( set +e; source "$CLIB"; rc_effective "$REG" - ) )
EFF_OFF=$(jq -c '.enabled = false' <<< "$EFF")
RT() {  # <state-file> <effective> <attempted> [role]
    ( set +e; CCT_ROUTING_STATE="$1" source "$REPO_DIR/scripts/lib/routing-select.sh"; rt_select "$2" "$3" "${4:-build}" )
}
verdict_of() { jq -r --arg id "$2" '.considered[] | select(.id == $id) | .verdict' <<< "$1"; }
reason_of()  { jq -r --arg id "$2" '.considered[] | select(.id == $id) | .reason'  <<< "$1"; }

# clean state: priority order, every candidate carries a verdict
SEL=$(RT "$TMP/sel-clean.json" "$EFF" '[]')
assert_eq "clean: the highest-priority tier1 build profile is selected" "alpha" "$(jq -r '.selected.id' <<< "$SEL")"
assert "clean: the selected reason journals unknown-not-healthy" \
    grep -q "state: unknown — never treated as healthy" <<< "$(reason_of "$SEL" alpha)"
assert_eq "clean: lower-priority eligibles are journaled, not dropped" "eligible eligible" \
    "$(printf '%s %s' "$(verdict_of "$SEL" beta)" "$(verdict_of "$SEL" delta)")"
assert_eq "clean: role filter is named" "rejected" "$(verdict_of "$SEL" rho)"
assert "clean: ...with the role in the reason" grep -q "does not hold role 'build'" <<< "$(reason_of "$SEL" rho)"
assert_eq "clean: tier2 is never selected (increment C owns it)" "rejected" "$(verdict_of "$SEL" gamma)"
assert_eq "clean: a tier2 profile HOLDING build at the best priority is still tier-rejected" "rejected" \
    "$(verdict_of "$SEL" sigma)"
assert "clean: ...for the TIER, not the role" \
    grep -q "tier1 only" <<< "$(reason_of "$SEL" sigma)"
assert_eq "clean: every candidate received a verdict" "6" "$(jq '.considered | length' <<< "$SEL")"
SEL2=$(RT "$TMP/sel-clean.json" "$EFF" '[]')
assert_eq "determinism: byte-identical selection on identical inputs" "$SEL" "$SEL2"

# attempted-set: bounded, cycle-free
SEL=$(RT "$TMP/sel-clean.json" "$EFF" '["alpha"]')
assert_eq "attempted alpha: the next priority is selected" "beta" "$(jq -r '.selected.id' <<< "$SEL")"
assert "attempted alpha: the reason is attempt-local" \
    grep -q "already attempted or incompatible in this unit" <<< "$(reason_of "$SEL" alpha)"

# pool block: the SIBLING is never burned (SC-B2 selector half)
PST="$TMP/sel-pool.json"
UNTIL=$(( $(date -u +%s) + 1800 ))
( set +e; CCT_ROUTING_STATE="$PST" source "$REPO_DIR/scripts/lib/routing-state.sh"; rs_set_pool sp-1 poolA cooldown "exhausted" "$UNTIL" ) >/dev/null 2>&1
SEL=$(RT "$PST" "$EFF" '[]')
assert_eq "pool cooled: BOTH poolA members are rejected, sibling never burned" "rejected rejected" \
    "$(printf '%s %s' "$(verdict_of "$SEL" alpha)" "$(verdict_of "$SEL" delta)")"
assert_eq "pool cooled: selection falls to the other pool" "beta" "$(jq -r '.selected.id' <<< "$SEL")"
assert_eq "shape 1: a SELECTED state carries no sleep target and no terminal reason" "null null" \
    "$(jq -r '"\(.earliest_retry) \(.terminal_reason)"' <<< "$SEL")"

# exhaustion: named reason from the closed enum + earliest wake time
XST="$TMP/sel-exh.json"
U2=$(( $(date -u +%s) + 900 ))
( set +e; CCT_ROUTING_STATE="$XST" source "$REPO_DIR/scripts/lib/routing-state.sh"
  rs_set_profile x1 alpha disabled "auth" -
  rs_set_pool x2 poolB cooldown "throttled" "$U2" ) >/dev/null 2>&1
SEL=$(RT "$XST" "$EFF" '["delta"]')
assert_eq "shape 2: TEMPORARY exhaustion — sleep target set, terminal reason NULL" \
    "true $U2 null" "$(jq -r '"\(.exhausted) \(.earliest_retry) \(.terminal_reason)"' <<< "$SEL")"
assert_eq "exhaustion: every blocking reason is present" "6" \
    "$(jq '[.considered[] | select(.verdict == "rejected")] | length' <<< "$SEL")"

# all blocks permanent -> no wake time to sleep toward
PMT="$TMP/sel-perm.json"
( set +e; CCT_ROUTING_STATE="$PMT" source "$REPO_DIR/scripts/lib/routing-state.sh"
  rs_set_profile p1 alpha disabled "auth" -
  rs_set_profile p2 beta disabled "auth" - ) >/dev/null 2>&1
SEL=$(RT "$PMT" "$EFF" '["delta"]')
assert_eq "shape 3: PERMANENT exhaustion — no sleep target, the terminal reason" \
    "true null routing_no_eligible_profile" \
    "$(jq -r '"\(.exhausted) \(.earliest_retry) \(.terminal_reason)"' <<< "$SEL")"

# effective policy disabled -> nothing selectable
SEL=$(RT "$TMP/sel-clean.json" "$EFF_OFF" '[]')
assert_eq "disabled policy: exhausted with every tier1 rejected" "true" "$(jq -r '.exhausted' <<< "$SEL")"
assert "disabled policy: the reason names the effective policy" \
    grep -q "disabled by the effective policy" <<< "$(reason_of "$SEL" alpha)"

# TIE-BREAK is policy, not declaration order: equal priorities resolve
# by id lexical ASC regardless of registry ordering.
tiereg() {  # <path> <first-id> <second-id>
    cat > "$1" <<TEOF
schema_version = 1

[route_classes.tier1_only]
tier_order = ["tier1"]

[[profiles]]
id = "$2"
backend = "claude-code"
provider = "p"
model = "m"
capability_tier = "tier1"
priority = 10
quota_pool = "poolT-$2"
roles = ["build"]
tool_profile = "t"
credential_mode = "login"
data_policy = "approved-cloud"

[[profiles]]
id = "$3"
backend = "claude-code"
provider = "p"
model = "m"
capability_tier = "tier1"
priority = 10
quota_pool = "poolT-$3"
roles = ["build"]
tool_profile = "t"
credential_mode = "login"
data_policy = "approved-cloud"
TEOF
}
tiereg "$TMP/tie1.toml" zeta eta
tiereg "$TMP/tie2.toml" eta zeta
EFF_T1=$( ( set +e; source "$CLIB"; rc_effective "$TMP/tie1.toml" - ) )
EFF_T2=$( ( set +e; source "$CLIB"; rc_effective "$TMP/tie2.toml" - ) )
ST1=$(RT "$TMP/tie-state.json" "$EFF_T1" '[]')
ST2=$(RT "$TMP/tie-state.json" "$EFF_T2" '[]')
assert_eq "tie-break: equal priority resolves by id (zeta-first registry)" "eta" "$(jq -r '.selected.id' <<< "$ST1")"
assert_eq "tie-break: ...and identically with the declaration reversed" "eta" "$(jq -r '.selected.id' <<< "$ST2")"
assert_eq "tie-break: the ordered consideration output is declaration-independent" \
    "$(jq -c '[.considered[].id]' <<< "$ST1")" "$(jq -c '[.considered[].id]' <<< "$ST2")"

# selected output is NAMED fields, never a positional tuple
SEL=$(RT "$TMP/sel-clean.json" "$EFF" '[]')
assert "selected is a named-field object (the tuple stays opaque)" \
    jq -e '.selected | (.id and .backend and .provider and .model and .pool and .tool_profile and (.credential_ref | length > 0))' <<< "$SEL"


echo ""
echo "=== T4: the supervisor --routing mode ==="
SUP="$REPO_DIR/scripts/cooldown-supervisor.sh"

# The scriptable mock harness: behavior per CCT_ROUTING_PROFILE comes
# from $MOCK_DIR/<profile>.spec (line N = invocation N: "<fixture>|<exit>";
# the last line repeats). Each invocation records its environment and
# bumps a per-profile counter — the assertions read those.
MOCK="$TMP/mock-harness.sh"
cat > "$MOCK" <<'MEOF'
#!/usr/bin/env bash
p="${CCT_ROUTING_PROFILE:-legacy}"
cnt_file="$MOCK_DIR/count-$p"
n=$(( $(cat "$cnt_file" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$cnt_file"
{ echo "backend=${CCT_AUTOBUILD_BACKEND:-}"
  echo "base_url=${ANTHROPIC_BASE_URL:-}"
  echo "api_key=${ANTHROPIC_API_KEY:-}"
  echo "profile=$p"
} > "$MOCK_DIR/env-$p-$n"
spec="$MOCK_DIR/$p.spec"
[[ -f "$spec" ]] || { echo "mock: no spec for $p"; exit 97; }
line=$(sed -n "${n}p" "$spec"); [[ -z "$line" ]] && line=$(tail -1 "$spec")
fixture="${line%%|*}"; code="${line##*|}"
[[ "$fixture" != "-" ]] && cat "$fixture"
exit "$code"
MEOF
chmod +x "$MOCK"
FXD="$SCRIPT_DIR/fixtures/routing"

# a registry: alpha (claude, endpoint+key refs) then beta (claude,
# DeepSeek-style refs) — and a pi-backend variant for cross-backend.
supreg() {  # <path> <second-backend: claude-code|pi>
    cat > "$1" <<SREOF
schema_version = 1

[route_classes.tier1_only]
tier_order = ["tier1"]

[[profiles]]
id = "alpha"
backend = "claude-code"
provider = "anthropic-subscription"
model = "sonnet"
capability_tier = "tier1"
priority = 10
quota_pool = "poolA"
roles = ["build"]
tool_profile = "full-cct"
credential_mode = "claude-login"
data_policy = "approved-cloud"

[[profiles]]
id = "beta"
backend = "$2"
provider = "deepseek-api"
model = "deepseek-v4"
capability_tier = "tier1"
priority = 20
quota_pool = "poolB"
roles = ["build"]
tool_profile = "deepseek-compatible"
base_url = "https://api.deepseek.example/anthropic"
credential_env = "CCT_T4_DS_KEY"
data_policy = "approved-cloud"
SREOF
}
supreg "$TMP/sup-reg.toml" claude-code
supreg "$TMP/sup-reg-pi.toml" pi

# sup_run <name> <registry> [extra supervisor args...] -> rc; artifacts
# under $TMP/<name>/ (workroot, mock dir, state, supervisor ledger)
SUP_RC=0
sup_run() {
    local name="$1" reg="$2"; shift 2
    local root="$TMP/$name"
    mkdir -p "$root/wr/specs/demo-feat" "$root/mock" "$root/led"
    printf -- "- [x] done\n" > "$root/wr/specs/demo-feat/tasks.md"
    SUP_RC=0
    ( set +e
      cd "$REPO_DIR"
      env MOCK_DIR="$root/mock" \
          CCT_T4_DS_KEY="t4-secret-value-77aa" \
          CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$root/mock' bash '$MOCK'" \
          CCT_SUPERVISOR_SLEEP=true \
          CCT_SUPERVISOR_DIR="$root/led" \
          CCT_ROUTING_REGISTRY="$reg" \
          CCT_ROUTING_STATE="$root/state.json" \
          bash "$SUP" demo-feat --routing --worktree "$root/wr" --profile unattended "$@" \
          > "$root/out.log" 2>&1 ) && SUP_RC=0 || SUP_RC=$?
}
spec() { printf '%s\n' "$2" > "$TMP/$1"; }

# ── refusals ──
OUT=$(CCT_ROUTING_REGISTRY="$TMP/absent.toml" bash -c "set +e; bash '$SUP' demo-feat --routing --worktree '$TMP' 2>&1"; exit 0)
assert "refusal: --routing without a registry names the opt-in path" \
    grep -q "requires a registry" <<< "$OUT"
DISREG="$TMP/dis-reg.toml"; supreg "$DISREG" claude-code
printf '\n[policy]\nenabled = false\n' >> "$DISREG"
OUT=$(CCT_ROUTING_REGISTRY="$DISREG" bash -c "set +e; bash '$SUP' demo-feat --routing --worktree '$TMP' 2>&1"; exit 0)
assert "refusal: an effective-disabled policy refuses, never silently falls back" \
    grep -q "DISABLED by the effective policy" <<< "$OUT"

# ── SC-B1/SC-B6: the quota failover chain, secrets child-env-only ──
mkdir -p "$TMP/chain/mock"
printf '%s\n' "$FXD/claude-weekly-limit.out|1" > "$TMP/chain/mock/alpha.spec"
printf '%s\n' "-|0" > "$TMP/chain/mock/beta.spec"
sup_run chain "$TMP/sup-reg.toml"
assert_eq "chain: the run COMPLETES on the fallback profile (exit 0)" "0" "$SUP_RC"
assert_eq "chain: alpha attempted once, beta once" "1 1" \
    "$(printf '%s %s' "$(cat "$TMP/chain/mock/count-alpha")" "$(cat "$TMP/chain/mock/count-beta")")"
assert_eq "chain: the quota event cooled the WHOLE pool" "cooldown" \
    "$(jq -r '.pools.poolA.state' "$TMP/chain/state.json")"
assert_eq "chain: ...until the provider reset instant" \
    "$(date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "2026-08-24T10:00:00Z" +%s 2>/dev/null || date -u -d "2026-08-24T10:00:00Z" +%s)" \
    "$(jq -r '.pools.poolA.until' "$TMP/chain/state.json")"
RTD="$TMP/chain/wr/.cct/auto-build/demo-feat/routing"
assert "chain: decision-5 artifacts exist for both attempts" \
    bash -c "[[ -f '$RTD/started-1.json' && -f '$RTD/result-1.json' && -f '$RTD/checkpoint-1.json' && -f '$RTD/started-2.json' && -f '$RTD/result-2.json' ]]"
assert_eq "chain: the state applied the attempt id idempotently" "true" \
    "$(jq --arg id "$(jq -r '.attempt_id' "$RTD/started-1.json")" '.applied | has($id)' "$TMP/chain/state.json")"
EVTS="$TMP/chain/led/demo-feat/events.jsonl"
assert "chain: every candidate verdict is journaled" \
    bash -c "grep -q 'routing_candidate' '$EVTS' && grep -q 'routing_failover' '$EVTS'"
assert "chain: beta received the endpoint and key IN ITS ENVIRONMENT" \
    bash -c "grep -q 'base_url=https://api.deepseek.example/anthropic' '$TMP/chain/mock/env-beta-1' && grep -q 'api_key=t4-secret-value-77aa' '$TMP/chain/mock/env-beta-1'"
assert_eq "chain: the secret value appears NOWHERE in ledger/journal/checkpoints" "0" \
    "$(grep -r "t4-secret-value-77aa" "$TMP/chain/led" "$RTD" 2>/dev/null | wc -l | tr -d ' ')"
assert "chain: the wired NAMES are journaled" \
    grep -q "ANTHROPIC_API_KEY(env:CCT_T4_DS_KEY)" "$EVTS"

# ── SC-B3: one same-profile rate retry, no failover ──
mkdir -p "$TMP/rate/mock"
printf '%s\n%s\n' "$FXD/api-429-text.out|1" "-|0" > "$TMP/rate/mock/alpha.spec"
printf '%s\n' "-|0" > "$TMP/rate/mock/beta.spec"
sup_run rate "$TMP/sup-reg.toml"
assert_eq "rate: completes on the SAME profile after one retry (exit 0)" "0" "$SUP_RC"
assert_eq "rate: alpha twice, beta NEVER" "2 no" \
    "$(printf '%s %s' "$(cat "$TMP/rate/mock/count-alpha")" "$( [[ -f "$TMP/rate/mock/count-beta" ]] && echo yes || echo no )")"
assert "rate: the single retry is journaled with its epoch-anchored wait" \
    grep -q "routing_retry_same" "$TMP/rate/led/demo-feat/events.jsonl"

# ── auth: disable exactly one profile, continue ──
mkdir -p "$TMP/auth/mock"
printf '%s\n' "$FXD/api-auth-structured.out|1" > "$TMP/auth/mock/alpha.spec"
printf '%s\n' "-|0" > "$TMP/auth/mock/beta.spec"
sup_run auth "$TMP/sup-reg.toml"
assert_eq "auth: run completes on the next profile" "0" "$SUP_RC"
assert_eq "auth: exactly alpha is disabled" "disabled" "$(jq -r '.profiles.alpha.state' "$TMP/auth/state.json")"

# ── denied and unknown: fail closed, nothing else launched ──
mkdir -p "$TMP/denied/mock"
printf '%s\n' "$FXD/amb-403-policy.out|1" > "$TMP/denied/mock/alpha.spec"
printf '%s\n' "-|0" > "$TMP/denied/mock/beta.spec"
sup_run denied "$TMP/sup-reg.toml"
assert_eq "denied: unattended terminates (exit 5), never rerouted" "5" "$SUP_RC"
assert "denied: the closed-enum reason reaches the ledger" \
    grep -q "routing_policy_denied" "$TMP/denied/led/demo-feat/run.json"
assert_eq "denied: the fallback profile was NEVER launched" "no" \
    "$( [[ -f "$TMP/denied/mock/count-beta" ]] && echo yes || echo no )"
mkdir -p "$TMP/unk/mock"
printf '%s\n' "$FXD/novel-unmatched.out|1" > "$TMP/unk/mock/alpha.spec"
printf '%s\n' "-|0" > "$TMP/unk/mock/beta.spec"
sup_run unk "$TMP/sup-reg.toml"
assert_eq "unknown: fails closed (exit 5), no failover" "5 no" \
    "$(printf '%s %s' "$SUP_RC" "$( [[ -f "$TMP/unk/mock/count-beta" ]] && echo yes || echo no )")"

# ── SC-B5: cross-backend handoff (claude-code -> pi) ──
mkdir -p "$TMP/xb/mock"
printf '%s\n' "$FXD/claude-session-limit.out|1" > "$TMP/xb/mock/alpha.spec"
printf '%s\n' "-|0" > "$TMP/xb/mock/beta.spec"
sup_run xb "$TMP/sup-reg-pi.toml"
assert_eq "cross-backend: completes via the pi backend" "0" "$SUP_RC"
assert "cross-backend: the second launch is a FRESH pi session" \
    grep -q "backend=pi" "$TMP/xb/mock/env-beta-1"
assert_eq "cross-backend: no session identifier crosses (fresh env per launch)" "0" \
    "$(grep -c "session" "$TMP/xb/mock/env-beta-1" || true)"

# ── SC-B7: tri-state model identity ──
MFIX="$TMP/model-mismatch.out"; printf '{"model":"deepseek-flash"}\nall done\n' > "$MFIX"
mkdir -p "$TMP/mid/mock"
printf '%s\n' "$MFIX|0" > "$TMP/mid/mock/alpha.spec"
printf '%s\n' "-|0" > "$TMP/mid/mock/beta.spec"
sup_run mid "$TMP/sup-reg.toml"
assert_eq "model mismatch: fails closed (exit 5), never rerouted" "5" "$SUP_RC"
assert "model mismatch: the named identity violation is recorded" \
    grep -q "routing_model_identity_mismatch" "$TMP/mid/led/demo-feat/run.json"
assert_eq "model mismatch: requested and effective retained SEPARATELY" "sonnet deepseek-flash" \
    "$(jq -r '.result | "\(.requested_model) \(.effective_model)"' "$TMP/mid/wr/.cct/auto-build/demo-feat/routing/result-1.json")"
mkdir -p "$TMP/unv/mock"
printf '%s\n' "-|0" > "$TMP/unv/mock/alpha.spec"
sup_run unv "$TMP/sup-reg.toml"
assert_eq "unverified model: the run proceeds" "0" "$SUP_RC"
assert "unverified model: journaled as UNVERIFIED, never assumed" \
    grep -q "effective model UNVERIFIED" "$TMP/unv/led/demo-feat/events.jsonl"
assert_eq "unverified model: recorded null in the result" "null" \
    "$(jq -r '.result.effective_model // "null"' "$TMP/unv/wr/.cct/auto-build/demo-feat/routing/result-1.json")"

# ── SC-B9: indeterminate recovery — never replay, never assume failure ──
mkdir -p "$TMP/ind/mock" "$TMP/ind/wr/.cct/auto-build/demo-feat/routing" "$TMP/ind/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/ind/wr/specs/demo-feat/tasks.md"
printf '{"attempt_id":"demo-feat-x-a1","attempt":1}' > "$TMP/ind/wr/.cct/auto-build/demo-feat/routing/started-1.json"
printf '%s\n' "-|0" > "$TMP/ind/mock/alpha.spec"
sup_run ind "$TMP/sup-reg.toml"
assert_eq "indeterminate: unattended terminates (exit 5)" "5" "$SUP_RC"
assert "indeterminate: the named reason with provenance" \
    grep -q "routing_attempt_indeterminate" "$TMP/ind/led/demo-feat/run.json"
assert "indeterminate: the SPECIFIC no-result diagnostic (not the malformed arm)" \
    grep -q "no terminal result was recorded" "$TMP/ind/led/demo-feat/events.jsonl"
assert_eq "indeterminate: the attempt was NEVER replayed" "no" \
    "$( [[ -f "$TMP/ind/mock/count-alpha" ]] && echo yes || echo no )"

# ── exhaustion shapes at the supervisor level ──
mkdir -p "$TMP/perm/mock"
printf '%s\n' "-|0" > "$TMP/perm/mock/alpha.spec"
( set +e; CCT_ROUTING_STATE="$TMP/perm/state.json" \
    bash -c "source '$REPO_DIR/scripts/lib/routing-state.sh'; rs_set_profile pre-1 alpha disabled auth -; rs_set_profile pre-2 beta disabled auth -" ) >/dev/null 2>&1
sup_run perm "$TMP/sup-reg.toml"
assert_eq "permanent exhaustion: terminates with the closed-enum reason" "5" "$SUP_RC"
assert "permanent exhaustion: routing_no_eligible_profile recorded" \
    grep -q "routing_no_eligible_profile" "$TMP/perm/led/demo-feat/run.json"
mkdir -p "$TMP/tmpx/mock"
printf '%s\n' "-|0" > "$TMP/tmpx/mock/alpha.spec"
( set +e; CCT_ROUTING_STATE="$TMP/tmpx/state.json" \
    bash -c "source '$REPO_DIR/scripts/lib/routing-state.sh'; rs_set_pool pre-3 poolA cooldown x $(( $(date -u +%s) + 999999 )); rs_set_pool pre-4 poolB cooldown x $(( $(date -u +%s) + 999999 ))" ) >/dev/null 2>&1
sup_run tmpx "$TMP/sup-reg.toml" --max-wall-sec 60
assert_eq "temporary exhaustion beyond the wall cap: refuses rather than oversleeping" "5" "$SUP_RC"
assert "temporary exhaustion: names the time-block and the cap" \
    grep -q "beyond the wall-clock cap" "$TMP/tmpx/led/demo-feat/run.json"

# ── terminated_policy precedence survives routing ──
QFIX="$TMP/quota-exit6.out"; cat "$FXD/claude-session-limit.out" > "$QFIX"
mkdir -p "$TMP/term/mock"
printf '%s\n' "$QFIX|6" > "$TMP/term/mock/alpha.spec"
printf '%s\n' "-|0" > "$TMP/term/mock/beta.spec"
sup_run term "$TMP/sup-reg.toml"
assert_eq "terminated_policy: exit 6 stays terminal even with quota-looking text" "6" "$SUP_RC"
assert_eq "terminated_policy: no cooldown state was invented" "null" \
    "$(jq -r '.pools.poolA // "null"' "$TMP/term/state.json" 2>/dev/null || echo null)"

# ── recovery: result-without-checkpoint applies the RECORDED decision,
#    NEVER relaunches ──
mk_result() {  # <dir> <n> <fixture> <exit> <retries> -> writes started+result
    local dir="$1" n="$2" fx="$3" code="$4" retries="$5"
    local pj='{"id":"alpha","backend":"claude-code","provider":"anthropic-subscription","model":"sonnet","tier":"tier1","priority":10,"pool":"poolA","roles":["build"],"tool_profile":"full-cct","data_policy":"approved-cloud","credential_ref":"mode:claude-login","endpoint_ref":"none"}'
    local epoch=1787400000
    ( set +e
      source "$REPO_DIR/scripts/lib/routing-result.sh"
      source "$REPO_DIR/scripts/lib/routing-actions.sh"
      res=$(rr_result "$code" "$fx" claude-code anthropic-subscription alpha sonnet - poolA - '{}')
      dec=$(ra_decide "$res" "$retries" "$epoch")
      mkdir -p "$dir"
      jq -n --argjson n "$n" --argjson p "$pj" --argjson t "$epoch" \
            --arg id "recov-a$n" \
            '{attempt_id:$id, attempt:$n, profile:$p, started_epoch:$t}' > "$dir/started-$n.json"
      jq -n --arg id "recov-a$n" --argjson t "$epoch" --argjson r "$res" --argjson d "$dec" \
            '{schema_version:1, attempt_id:$id, decision_epoch:$t, result:$r, decision:$d, legacy_usage_fallback:null}' > "$dir/result-$n.json" )
}
# R1: denied result, action never applied -> recovery parks with the
# recorded reason; the child is NEVER launched; the checkpoint appears.
mkdir -p "$TMP/rec1/mock" "$TMP/rec1/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/rec1/wr/specs/demo-feat/tasks.md"
printf '%s\n' "-|0" > "$TMP/rec1/mock/alpha.spec"
mk_result "$TMP/rec1/wr/.cct/auto-build/demo-feat/routing" 1 "$FXD/amb-403-policy.out" 1 0
sup_run rec1 "$TMP/sup-reg.toml"
assert_eq "recovery/denied: the recorded park applies without relaunch" "5" "$SUP_RC"
assert "recovery/denied: the recorded reason survives" \
    grep -q "routing_policy_denied" "$TMP/rec1/led/demo-feat/run.json"
assert_eq "recovery/denied: the child was NEVER launched" "no" \
    "$( [[ -f "$TMP/rec1/mock/count-alpha" ]] && echo yes || echo no )"
assert "recovery/denied: the checkpoint was published" \
    test -f "$TMP/rec1/wr/.cct/auto-build/demo-feat/routing/checkpoint-1.json"
assert "recovery/denied: the recovery is journaled as no-relaunch" \
    grep -q "applying the recorded decision WITHOUT relaunching" "$TMP/rec1/led/demo-feat/events.jsonl"

# R2: auth result, action ALREADY applied, checkpoint missing ->
# idempotent no-op, checkpoint published, the run then continues on beta.
mkdir -p "$TMP/rec2/mock" "$TMP/rec2/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/rec2/wr/specs/demo-feat/tasks.md"
printf '%s\n' "-|0" > "$TMP/rec2/mock/beta.spec"
printf '%s\n' "-|0" > "$TMP/rec2/mock/alpha.spec"
mk_result "$TMP/rec2/wr/.cct/auto-build/demo-feat/routing" 1 "$FXD/api-auth-structured.out" 1 0
( set +e; CCT_ROUTING_STATE="$TMP/rec2/state.json" \
    bash -c "source '$REPO_DIR/scripts/lib/routing-state.sh'; rs_set_profile recov-a1 alpha disabled 'credential or billing rejection' -" ) >/dev/null 2>&1
sup_run rec2 "$TMP/sup-reg.toml"
assert_eq "recovery/applied: completes on beta (exit 0)" "0" "$SUP_RC"
assert_eq "recovery/applied: alpha never relaunched, beta exactly once" "no 1" \
    "$(printf '%s %s' "$( [[ -f "$TMP/rec2/mock/count-alpha" ]] && echo yes || echo no )" "$(cat "$TMP/rec2/mock/count-beta")")"
assert "recovery/applied: the state replay was an idempotent no-op" \
    grep -q "idempotent no-op" "$TMP/rec2/led/demo-feat/events.jsonl"
assert "recovery/applied: the checkpoint was published" \
    test -f "$TMP/rec2/wr/.cct/auto-build/demo-feat/routing/checkpoint-1.json"

# R3: a MALFORMED result is not durable evidence -> indeterminate.
mkdir -p "$TMP/rec3/mock" "$TMP/rec3/wr/.cct/auto-build/demo-feat/routing" "$TMP/rec3/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/rec3/wr/specs/demo-feat/tasks.md"
printf '%s\n' "-|0" > "$TMP/rec3/mock/alpha.spec"
printf '{"attempt_id":"x","attempt":1}' > "$TMP/rec3/wr/.cct/auto-build/demo-feat/routing/started-1.json"
printf '{"attempt_id":"x","result":{' > "$TMP/rec3/wr/.cct/auto-build/demo-feat/routing/result-1.json"
sup_run rec3 "$TMP/sup-reg.toml"
assert_eq "recovery/malformed: fails closed as indeterminate" "5" "$SUP_RC"
assert "recovery/malformed: named as a malformed terminal result" \
    grep -q "routing_attempt_indeterminate" "$TMP/rec3/led/demo-feat/run.json"
assert_eq "recovery/malformed: never launched" "no" \
    "$( [[ -f "$TMP/rec3/mock/count-alpha" ]] && echo yes || echo no )"

# R4: control replay — retry counts are attempt-id idempotent across
# the crash window between the control write and the checkpoint.
mkdir -p "$TMP/rec4/mock" "$TMP/rec4/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/rec4/wr/specs/demo-feat/tasks.md"
printf '%s\n' "-|0" > "$TMP/rec4/mock/alpha.spec"
mk_result "$TMP/rec4/wr/.cct/auto-build/demo-feat/routing" 1 "$FXD/api-429-text.out" 1 0
jq -n '{epoch_attempted:[], attempt_local_excluded:[], retry_counts:{alpha:1}, applied_attempts:["recov-a1"]}' \
    > "$TMP/rec4/wr/.cct/auto-build/demo-feat/routing/control.json"
sup_run rec4 "$TMP/sup-reg.toml"
assert_eq "control-replay: the run completes (the retry proceeds once)" "0" "$SUP_RC"
assert_eq "control-replay: attempt 1 was never relaunched (only the single retry ran)" "1" \
    "$(cat "$TMP/rec4/mock/count-alpha")"
assert_eq "control-replay: the retry budget stayed EXACTLY 1" "1" \
    "$(jq -r '.retry_counts.alpha' "$TMP/rec4/wr/.cct/auto-build/demo-feat/routing/control.json")"
assert "control-replay: the replay is journaled as a control no-op" \
    grep -q "routing_control_noop" "$TMP/rec4/led/demo-feat/events.jsonl"
assert "control-replay: the checkpoint was published" \
    test -f "$TMP/rec4/wr/.cct/auto-build/demo-feat/routing/checkpoint-1.json"

# the other crash half is rec2 (T1 state applied, control not): extend
# its proof — the control effect applied exactly once on recovery.
assert_eq "recovery/applied: the control effect landed exactly once" '["alpha"]' \
    "$(jq -c '.epoch_attempted' "$TMP/rec2/wr/.cct/auto-build/demo-feat/routing/control.json")"
assert "recovery/applied: ...with its attempt id marked in the SAME write" \
    bash -c "jq -e '.applied_attempts | index(\"recov-a1\") != null' '$TMP/rec2/wr/.cct/auto-build/demo-feat/routing/control.json'"

# R5: the envelope is VERSIONED and CLOSED — recovery acts only on a
# valid v1 envelope; anything else is indeterminate with ZERO effects.
mkdir -p "$TMP/rec5/mock" "$TMP/rec5/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/rec5/wr/specs/demo-feat/tasks.md"
printf '%s\n' "-|0" > "$TMP/rec5/mock/alpha.spec"
mk_result "$TMP/rec5/wr/.cct/auto-build/demo-feat/routing" 1 "$FXD/api-auth-structured.out" 1 0
jq '.schema_version = 2' "$TMP/rec5/wr/.cct/auto-build/demo-feat/routing/result-1.json" > "$TMP/rec5/v2.json" \
    && mv "$TMP/rec5/v2.json" "$TMP/rec5/wr/.cct/auto-build/demo-feat/routing/result-1.json"
sup_run rec5 "$TMP/sup-reg.toml"
assert_eq "envelope/version: an unknown schema_version is indeterminate" "5" "$SUP_RC"
assert "envelope/version: named as a foreign-version envelope" \
    grep -q "foreign-version terminal result envelope" "$TMP/rec5/led/demo-feat/events.jsonl"
assert_eq "envelope/version: zero relaunches" "no" \
    "$( [[ -f "$TMP/rec5/mock/count-alpha" ]] && echo yes || echo no )"
assert_eq "envelope/version: zero state mutations" "no" \
    "$( [[ -f "$TMP/rec5/state.json" ]] && echo yes || echo no )"
mkdir -p "$TMP/rec6/mock" "$TMP/rec6/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/rec6/wr/specs/demo-feat/tasks.md"
printf '%s\n' "-|0" > "$TMP/rec6/mock/alpha.spec"
mk_result "$TMP/rec6/wr/.cct/auto-build/demo-feat/routing" 1 "$FXD/api-auth-structured.out" 1 0
jq '.surprise = true' "$TMP/rec6/wr/.cct/auto-build/demo-feat/routing/result-1.json" > "$TMP/rec6/x.json" \
    && mv "$TMP/rec6/x.json" "$TMP/rec6/wr/.cct/auto-build/demo-feat/routing/result-1.json"
sup_run rec6 "$TMP/sup-reg.toml"
assert_eq "envelope/closed: an unexpected field is indeterminate (zero effects)" "5 no" \
    "$(printf '%s %s' "$SUP_RC" "$( [[ -f "$TMP/rec6/mock/count-alpha" ]] && echo yes || echo no )")"

# R7: replay identity is the PERSISTED one — a mutated registry cannot
# retarget the recovered action.
mkdir -p "$TMP/rec7/mock" "$TMP/rec7/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/rec7/wr/specs/demo-feat/tasks.md"
printf '%s\n' "-|0" > "$TMP/rec7/mock/alpha.spec"
mk_result "$TMP/rec7/wr/.cct/auto-build/demo-feat/routing" 1 "$FXD/claude-weekly-limit.out" 1 0
MUTREG="$TMP/rec7-reg.toml"
cat > "$MUTREG" <<MREOF
schema_version = 1

[route_classes.tier1_only]
tier_order = ["tier1"]

[[profiles]]
id = "alpha"
backend = "claude-code"
provider = "somewhere-else"
model = "other-model"
capability_tier = "tier1"
priority = 10
quota_pool = "poolZ"
roles = ["build"]
tool_profile = "t"
credential_mode = "claude-login"
data_policy = "approved-cloud"
MREOF
sup_run rec7 "$MUTREG"
assert_eq "replay-identity: the recorded quota action cooled the ORIGINAL pool" "cooldown" \
    "$(jq -r '.pools.poolA.state // "absent"' "$TMP/rec7/state.json")"
assert_eq "replay-identity: the mutated registry's pool was NEVER touched" "absent" \
    "$(jq -r '.pools.poolZ.state // "absent"' "$TMP/rec7/state.json")"
assert_eq "replay-identity: attempt 1 was never relaunched" "no" \
    "$( [[ -f "$TMP/rec7/mock/count-alpha" ]] && echo yes || echo no )"

# ── sticky exclusions: a sleep resets ONLY the eligibility-window set ──
mkdir -p "$TMP/sticky/mock"
printf '%s\n' "$FXD/vllm-context-overflow.out|1" > "$TMP/sticky/mock/alpha.spec"
printf '%s\n' "-|0" > "$TMP/sticky/mock/beta.spec"
( set +e; CCT_ROUTING_STATE="$TMP/sticky/state.json" \
    bash -c "source '$REPO_DIR/scripts/lib/routing-state.sh'; rs_set_profile pre-s beta cooldown throttled $(( $(date -u +%s) + 6 ))" ) >/dev/null 2>&1
mkdir -p "$TMP/sticky/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/sticky/wr/specs/demo-feat/tasks.md"
( set +e
  cd "$REPO_DIR"
  env MOCK_DIR="$TMP/sticky/mock" \
      CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$TMP/sticky/mock' bash '$MOCK'" \
      CCT_SUPERVISOR_DIR="$TMP/sticky/led" \
      CCT_ROUTING_REGISTRY="$TMP/sup-reg.toml" \
      CCT_ROUTING_STATE="$TMP/sticky/state.json" \
      bash "$SUP" demo-feat --routing --worktree "$TMP/sticky/wr" --profile unattended \
      > "$TMP/sticky/out.log" 2>&1 ) && SRC=0 || SRC=$?
assert_eq "sticky: the run completes on beta after the REAL eligibility sleep" "0" "$SRC"
assert_eq "sticky: the incompatible profile was NEVER retried after the sleep" "1" \
    "$(cat "$TMP/sticky/mock/count-alpha")"
CTRL="$TMP/sticky/wr/.cct/auto-build/demo-feat/routing/control.json"
assert_eq "sticky: the request-local exclusion is DURABLE" '["alpha"]' \
    "$(jq -c '.attempt_local_excluded' "$CTRL")"
assert "sticky: the sleep journals that exclusions/budgets are preserved" \
    grep -q "request-local exclusions and retry budgets are PRESERVED" "$TMP/sticky/led/demo-feat/events.jsonl"

# ── retry budgets are durable control state ──
assert_eq "budget: the consumed same-profile retry is durably recorded" "1" \
    "$(jq -r '.retry_counts.alpha' "$TMP/rate/wr/.cct/auto-build/demo-feat/routing/control.json")"

# ── credential taint: an ECHOING child cannot persist the secret ──
mkdir -p "$TMP/taint/mock" "$TMP/taint/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/taint/wr/specs/demo-feat/tasks.md"
ECHOFX="$TMP/echo-key.out"
printf '#!/bin/bash\necho "leaked=$ANTHROPIC_API_KEY"\ncat "%s"\nexit 1\n' "$FXD/claude-session-limit.out" > "$TMP/taint-mock.sh"
cat > "$TMP/taint/mock-wrapper.sh" <<WEOF
#!/usr/bin/env bash
if [[ "\${CCT_ROUTING_PROFILE}" == "beta" ]]; then
  echo "leaked=\${ANTHROPIC_API_KEY}"
  cat "$FXD/claude-session-limit.out"
  n_file="\$MOCK_DIR/count-beta"; echo \$(( \$(cat "\$n_file" 2>/dev/null || echo 0) + 1 )) > "\$n_file"
  exit 1
fi
MOCK_DIR="\$MOCK_DIR" bash "$MOCK"
WEOF
chmod +x "$TMP/taint/mock-wrapper.sh"
printf '%s\n' "$FXD/claude-weekly-limit.out|1" > "$TMP/taint/mock/alpha.spec"
( set +e
  cd "$REPO_DIR"
  env MOCK_DIR="$TMP/taint/mock" \
      CCT_T4_DS_KEY="t4-secret-value-77aa" \
      CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$TMP/taint/mock' bash '$TMP/taint/mock-wrapper.sh'" \
      CCT_SUPERVISOR_SLEEP=true CCT_SUPERVISOR_DIR="$TMP/taint/led" \
      CCT_ROUTING_REGISTRY="$TMP/sup-reg.toml" \
      CCT_ROUTING_STATE="$TMP/taint/state.json" \
      bash "$SUP" demo-feat --routing --worktree "$TMP/taint/wr" --profile unattended --max-attempts 3 \
      > "$TMP/taint/out.log" 2>&1 ) || true
TRTD="$TMP/taint/wr/.cct/auto-build/demo-feat/routing"
assert_eq "taint: the echoed secret reaches NO durable artifact" "0" \
    "$(grep -r "t4-secret-value-77aa" "$TMP/taint/led" "$TRTD" 2>/dev/null | wc -l | tr -d ' ')"
assert "taint: the transcript carries the redaction marker instead" \
    grep -q "REDACTED:ANTHROPIC_API_KEY" "$TRTD/transcript-2.log"

# ── SC-B10: without the flag, a present registry changes NOTHING ──
mkdir -p "$TMP/leg/mock" "$TMP/leg/wr/specs/demo-feat" "$TMP/leg/led"
printf -- "- [x] done\n" > "$TMP/leg/wr/specs/demo-feat/tasks.md"
( set +e; cd "$REPO_DIR"
  env MOCK_DIR="$TMP/leg/mock" \
      CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$TMP/leg/mock' bash '$MOCK'" \
      CCT_SUPERVISOR_SLEEP=true CCT_SUPERVISOR_DIR="$TMP/leg/led" \
      CCT_ROUTING_REGISTRY="$TMP/sup-reg.toml" \
      bash "$SUP" demo-feat --worktree "$TMP/leg/wr" --profile unattended \
      > "$TMP/leg/out.log" 2>&1 ) && LRC=0 || LRC=$?
printf '%s\n' "-|0" > "$TMP/leg/mock/legacy.spec"
( set +e; cd "$REPO_DIR"
  env MOCK_DIR="$TMP/leg/mock" \
      CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$TMP/leg/mock' bash '$MOCK'" \
      CCT_SUPERVISOR_SLEEP=true CCT_SUPERVISOR_DIR="$TMP/leg/led2" \
      CCT_ROUTING_REGISTRY="$TMP/sup-reg.toml" \
      bash "$SUP" demo-feat --worktree "$TMP/leg/wr" --profile unattended \
      > "$TMP/leg/out2.log" 2>&1 ) && LRC=0 || LRC=$?
assert_eq "legacy: without --routing the registry is inert (clean done path)" "0" "$LRC"
assert_eq "legacy: no routing artifacts are created" "no" \
    "$( [[ -d "$TMP/leg/wr/.cct/auto-build/demo-feat/routing" ]] && echo yes || echo no )"


echo ""
echo "=== T5: builder identity + reviewer independence ==="

# providers fixtures (READ ONLY — never a second routing registry)
mkprov() {  # <path> <reviewer-model> [reviewer-provider]
    cat > "$1" <<PEOF
[defaults]
peer_for.claude = "rev1"
peer_for.pi = "rev1"

[providers.rev1]
type = "api"
model = "$2"
${3:+provider = "$3"}
PEOF
}
# collision: the gating reviewer IS the builder's model -> refuse
# BEFORE any launch and BEFORE any durable attempt record.
mkdir -p "$TMP/indep1/mock" "$TMP/indep1/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/indep1/wr/specs/demo-feat/tasks.md"
printf '%s\n' "-|0" > "$TMP/indep1/mock/alpha.spec"
mkprov "$TMP/indep1/providers.toml" "sonnet"
( set +e
  cd "$REPO_DIR"
  env MOCK_DIR="$TMP/indep1/mock" \
      CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$TMP/indep1/mock' bash '$MOCK'" \
      CCT_SUPERVISOR_SLEEP=true CCT_SUPERVISOR_DIR="$TMP/indep1/led" \
      CCT_ROUTING_REGISTRY="$TMP/sup-reg.toml" \
      CCT_ROUTING_STATE="$TMP/indep1/state.json" \
      CCT_PROVIDERS_PROFILE="$TMP/indep1/providers.toml" \
      bash "$SUP" demo-feat --routing --worktree "$TMP/indep1/wr" --profile unattended \
      > "$TMP/indep1/out.log" 2>&1 ) && IRC=0 || IRC=$?
assert_eq "independence/collision: terminal, never downgraded (exit 5)" "5" "$IRC"
assert "independence/collision: the closed-enum reason is recorded" \
    grep -q "routing_reviewer_not_independent" "$TMP/indep1/led/demo-feat/run.json"
assert "independence/collision: same-model stays a conservative signal across distinct providers" \
    grep -q "the same MODEL ('sonnet') despite distinct providers" "$TMP/indep1/led/demo-feat/events.jsonl"
assert_eq "independence/collision: the child was NEVER launched" "no" \
    "$( [[ -f "$TMP/indep1/mock/count-alpha" ]] && echo yes || echo no )"
assert_eq "independence/collision: NO dangling started record (the gate precedes step 1)" "no" \
    "$( [[ -f "$TMP/indep1/wr/.cct/auto-build/demo-feat/routing/started-1.json" ]] && echo yes || echo no )"

# independent reviewer -> proceeds and journals the evaluation
mkdir -p "$TMP/indep2/mock" "$TMP/indep2/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/indep2/wr/specs/demo-feat/tasks.md"
printf '%s\n' "-|0" > "$TMP/indep2/mock/alpha.spec"
mkprov "$TMP/indep2/providers.toml" "some-other-model"
( set +e
  cd "$REPO_DIR"
  env MOCK_DIR="$TMP/indep2/mock" \
      CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$TMP/indep2/mock' bash '$MOCK'" \
      CCT_SUPERVISOR_SLEEP=true CCT_SUPERVISOR_DIR="$TMP/indep2/led" \
      CCT_ROUTING_REGISTRY="$TMP/sup-reg.toml" \
      CCT_ROUTING_STATE="$TMP/indep2/state.json" \
      CCT_PROVIDERS_PROFILE="$TMP/indep2/providers.toml" \
      bash "$SUP" demo-feat --routing --worktree "$TMP/indep2/wr" --profile unattended \
      > "$TMP/indep2/out.log" 2>&1 ) && IRC=0 || IRC=$?
assert_eq "independence/ok: an independent reviewer lets the run proceed" "0" "$IRC"
assert "independence/ok: the established evaluation carries BOTH identities" \
    grep -q "independence=established: reviewer 'rev1' (provider 'rev1'" "$TMP/indep2/led/demo-feat/events.jsonl"

# unevaluable identity: journaled, NOT terminal (only a positive
# collision blocks; the driver's review machinery still governs)
mkdir -p "$TMP/indep3/mock" "$TMP/indep3/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/indep3/wr/specs/demo-feat/tasks.md"
printf '%s\n' "-|0" > "$TMP/indep3/mock/alpha.spec"
( set +e
  cd "$REPO_DIR"
  env MOCK_DIR="$TMP/indep3/mock" \
      CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$TMP/indep3/mock' bash '$MOCK'" \
      CCT_SUPERVISOR_SLEEP=true CCT_SUPERVISOR_DIR="$TMP/indep3/led" \
      CCT_ROUTING_REGISTRY="$TMP/sup-reg.toml" \
      CCT_ROUTING_STATE="$TMP/indep3/state.json" \
      CCT_PROVIDERS_PROFILE="$TMP/indep3/absent.toml" \
      bash "$SUP" demo-feat --routing --worktree "$TMP/indep3/wr" --profile unattended \
      > "$TMP/indep3/out.log" 2>&1 ) && IRC=0 || IRC=$?
assert_eq "independence/unevaluable: journaled, run proceeds" "0" "$IRC"
assert "independence/unevaluable: journaled as independence=unevaluable (never as independent)" \
    grep -q "independence=unevaluable: no providers profile" "$TMP/indep3/led/demo-feat/events.jsonl"

# same PROVIDER, different model: the PRIMARY collision signal —
# model inequality never substitutes for provider independence.
mkdir -p "$TMP/indep5/mock" "$TMP/indep5/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/indep5/wr/specs/demo-feat/tasks.md"
printf '%s\n' "-|0" > "$TMP/indep5/mock/alpha.spec"
mkprov "$TMP/indep5/providers.toml" "not-sonnet-at-all" "anthropic-subscription"
( set +e
  cd "$REPO_DIR"
  env MOCK_DIR="$TMP/indep5/mock" \
      CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$TMP/indep5/mock' bash '$MOCK'" \
      CCT_SUPERVISOR_SLEEP=true CCT_SUPERVISOR_DIR="$TMP/indep5/led" \
      CCT_ROUTING_REGISTRY="$TMP/sup-reg.toml" \
      CCT_ROUTING_STATE="$TMP/indep5/state.json" \
      CCT_PROVIDERS_PROFILE="$TMP/indep5/providers.toml" \
      bash "$SUP" demo-feat --routing --worktree "$TMP/indep5/wr" --profile unattended \
      > "$TMP/indep5/out.log" 2>&1 ) && IRC=0 || IRC=$?
assert_eq "independence/provider: same provider + DIFFERENT model is a collision" "5" "$IRC"
assert "independence/provider: the collision names the shared provider" \
    grep -q "the same PROVIDER ('anthropic-subscription')" "$TMP/indep5/led/demo-feat/events.jsonl"
assert_eq "independence/provider: nothing launched past the gate" "no" \
    "$( [[ -f "$TMP/indep5/mock/count-alpha" ]] && echo yes || echo no )"

# re-evaluation happens at EVERY switch, not only at start: alpha is
# independent; the FAILOVER target beta collides with the reviewer.
mkdir -p "$TMP/indep4/mock" "$TMP/indep4/wr/specs/demo-feat"
printf -- "- [x] done\n" > "$TMP/indep4/wr/specs/demo-feat/tasks.md"
printf '%s\n' "$FXD/claude-weekly-limit.out|1" > "$TMP/indep4/mock/alpha.spec"
printf '%s\n' "-|0" > "$TMP/indep4/mock/beta.spec"
mkprov "$TMP/indep4/providers.toml" "totally-different-model" "deepseek-api"   # PROVIDER collision with BETA only
( set +e
  cd "$REPO_DIR"
  env MOCK_DIR="$TMP/indep4/mock" \
      CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$TMP/indep4/mock' bash '$MOCK'" \
      CCT_SUPERVISOR_SLEEP=true CCT_SUPERVISOR_DIR="$TMP/indep4/led" \
      CCT_ROUTING_REGISTRY="$TMP/sup-reg.toml" \
      CCT_ROUTING_STATE="$TMP/indep4/state.json" \
      CCT_PROVIDERS_PROFILE="$TMP/indep4/providers.toml" \
      bash "$SUP" demo-feat --routing --worktree "$TMP/indep4/wr" --profile unattended \
      > "$TMP/indep4/out.log" 2>&1 ) && IRC=0 || IRC=$?
assert_eq "independence/switch: re-evaluated for the FAILOVER target (terminal)" "5" "$IRC"
assert_eq "independence/switch: alpha ran (independent), beta NEVER did (collision)" "1 no" \
    "$(printf '%s %s' "$(cat "$TMP/indep4/mock/count-alpha")" "$( [[ -f "$TMP/indep4/mock/count-beta" ]] && echo yes || echo no )")"
assert "independence/switch: a PROVIDER-level collision, models differing" \
    grep -q "COLLISION: gating reviewer 'rev1' resolves to the same PROVIDER ('deepseek-api')" "$TMP/indep4/led/demo-feat/events.jsonl"

# the emission chokepoint: an un-enum'd reason cannot escape rt_refuse
assert "chokepoint: rt_refuse validates every terminal reason" \
    grep -q "routing_enum_violation" "$REPO_DIR/scripts/cooldown-supervisor.sh"
assert_eq "identity: the env carries the FULL identity (pool + tool profile)" "2" \
    "$(grep -c "CCT_ROUTING_POOL\|CCT_ROUTING_TOOL_PROFILE" "$REPO_DIR/scripts/cooldown-supervisor.sh" | head -1)"

# identity propagation surfaces (structure pins; the driver and runner
# suites execute these paths in the sweep)
assert "identity: the driver ledger records routing_identity from the routed env" \
    grep -q "routing_identity" "$REPO_DIR/scripts/auto-build-loop.sh"
assert "identity: ...as null for unrouted runs (additive, never breaking)" \
    bash -c "grep -A2 'routing_identity' '$REPO_DIR/scripts/auto-build-loop.sh' | grep -q 'else {profile:\$rprof'"
assert "identity: the review request carries the builder identity line" \
    grep -q "Builder identity: profile %s" "$REPO_DIR/scripts/review-round-runner.sh"
assert "identity: the enum gained the independence disposition" \
    bash -c "source '$REPO_DIR/scripts/lib/routing-actions.sh'; ra_terminal_valid routing_reviewer_not_independent"
echo ""
echo "========================================="
echo "  routing-failover tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_FAILOVER_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_FAILOVER_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
