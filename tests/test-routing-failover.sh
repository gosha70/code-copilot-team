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
echo "========================================="
echo "  routing-failover tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_FAILOVER_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_FAILOVER_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
