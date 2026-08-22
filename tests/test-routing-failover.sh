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
assert_eq "pool cooled: earliest_retry is the pool's until" "$UNTIL" "$(jq -r '.earliest_retry' <<< "$SEL")"

# exhaustion: named reason from the closed enum + earliest wake time
XST="$TMP/sel-exh.json"
U2=$(( $(date -u +%s) + 900 ))
( set +e; CCT_ROUTING_STATE="$XST" source "$REPO_DIR/scripts/lib/routing-state.sh"
  rs_set_profile x1 alpha disabled "auth" -
  rs_set_pool x2 poolB cooldown "throttled" "$U2" ) >/dev/null 2>&1
SEL=$(RT "$XST" "$EFF" '["delta"]')
assert_eq "exhaustion: no eligible profile -> exhausted + the closed-enum reason" \
    "true routing_no_eligible_profile" "$(jq -r '"\(.exhausted) \(.terminal_reason)"' <<< "$SEL")"
assert_eq "exhaustion: every blocking reason is present" "6" \
    "$(jq '[.considered[] | select(.verdict == "rejected")] | length' <<< "$SEL")"
assert_eq "exhaustion: earliest_retry = the soonest time-based unblock" "$U2" "$(jq -r '.earliest_retry' <<< "$SEL")"

# all blocks permanent -> no wake time to sleep toward
PMT="$TMP/sel-perm.json"
( set +e; CCT_ROUTING_STATE="$PMT" source "$REPO_DIR/scripts/lib/routing-state.sh"
  rs_set_profile p1 alpha disabled "auth" -
  rs_set_profile p2 beta disabled "auth" - ) >/dev/null 2>&1
SEL=$(RT "$PMT" "$EFF" '["delta"]')
assert_eq "permanent exhaustion: earliest_retry is null (nothing to wait for)" "true null" \
    "$(jq -r '"\(.exhausted) \(.earliest_retry)"' <<< "$SEL")"

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
echo "========================================="
echo "  routing-failover tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_FAILOVER_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_FAILOVER_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
