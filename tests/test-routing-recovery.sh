#!/usr/bin/env bash
# test-routing-recovery.sh — #257 (increment D of #109) T1: the state
# extension (closed vocabulary; circuit state vs probe EXECUTION
# marker vs probe EVIDENCE kept distinct) and recovery timing
# (precedence chain, deterministic jitter, bounded backoff).
#
# Run from the repo root: bash tests/test-routing-recovery.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
SLIB="$REPO_DIR/scripts/lib/routing-state.sh"
RLIB="$REPO_DIR/scripts/lib/routing-recovery.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/cct-rrec.XXXXXX")"
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
# S <state-file> <fn> <args...> — run a store fn against a fixture
S() { ( set +e; CCT_ROUTING_STATE="$1" source "$SLIB"; "${@:2}" ); }
SE() { S "$@" 2>/dev/null; }
R() { ( set +e; source "$RLIB"; "$@" ); }
NOW=$(date -u +%s)

echo "== T1.1: the closed vocabulary + evidence-only health =="

ST="$TMP/vocab.json"
assert "vocabulary: the seven states are closed and validated" \
    bash -c "source '$SLIB'; for s in unknown cooldown disabled healthy degraded probe_due probing; do rs_state_valid \$s || exit 1; done"
assert "vocabulary: an unlisted state is refused" \
    bash -c "source '$SLIB'; ! rs_state_valid ready"
assert_eq "vocabulary: exactly seven states" "7" \
    "$(bash -c "source '$SLIB'; printf '%s\n' \$RS_STATES | wc -l | tr -d ' '")"

# health is enterable ONLY through evidence — the generic setters
# refuse it, so no call site can mint a health claim
out=$(S "$ST" rs_set_profile s1 alpha healthy "sneak" - 2>&1) && rc=0 || rc=$?
assert_eq "setter: rs_set_profile REFUSES healthy (evidence-only)" "1" "$rc"
assert "setter: the refusal names the evidence requirement" \
    grep -q "healthy requires real evidence" <<< "$out"
out=$(S "$ST" rs_set_pool s2 poolA healthy "sneak" - 2>&1) && rc=0 || rc=$?
assert_eq "setter: rs_set_pool REFUSES healthy" "1" "$rc"
for marker in probing probe_due; do
    out=$(S "$ST" rs_set_profile "s-$marker" alpha "$marker" "sneak" - 2>&1) && rc=0 || rc=$?
    assert_eq "setter: rs_set_profile refuses the execution marker '$marker'" "1" "$rc"
done
assert "setter: B's own states still write (cooldown)" \
    bash -c "CCT_ROUTING_STATE='$ST' bash -c \"source '$SLIB'; rs_set_profile ok1 beta cooldown rate $((NOW + 600))\""
assert_eq "setter: B's cooldown reads back unchanged" "cooldown" "$(SE "$ST" rs_effective_state beta poolB)"

echo ""
echo "== T1.2: probe lifecycle — schedule, in-flight, evidence =="

L="$TMP/life.json"
S "$L" rs_schedule_probe sc1 alpha $((NOW - 10)) "cooldown expired" >/dev/null 2>&1
assert_eq "schedule: state becomes the probe_due marker" "probe_due" "$(SE "$L" rs_effective_state alpha poolA)"
assert_eq "schedule: the due query finds it" "alpha" "$(SE "$L" rs_due_probes "$NOW")"
assert_eq "schedule: evidence counters untouched by scheduling" "0" \
    "$(SE "$L" rs_probe_evidence alpha | cut -f1)"

S "$L" rs_probe_begin bg1 alpha 7 >/dev/null 2>&1
assert_eq "in-flight: the marker is 'probing'" "probing" "$(SE "$L" rs_effective_state alpha poolA)"
assert_eq "in-flight: an in-flight probe is NOT a health claim" "no" \
    "$( [[ "$(SE "$L" rs_effective_state alpha poolA)" == "healthy" ]] && echo yes || echo no )"
assert_eq "in-flight: an in-flight probe is NOT a degradation" "no" \
    "$( [[ "$(SE "$L" rs_effective_state alpha poolA)" =~ ^(cooldown|disabled|degraded)$ ]] && echo yes || echo no )"
assert_eq "in-flight: the generation is recorded as evidence" "7" \
    "$(SE "$L" rs_probe_evidence alpha | cut -f4)"
assert_eq "in-flight: success counter still untouched" "0" \
    "$(SE "$L" rs_probe_evidence alpha | cut -f1)"

S "$L" rs_probe_pass pp1 alpha 2 >/dev/null 2>&1
assert_eq "evidence: one pass below threshold does NOT reach healthy" "probe_due" \
    "$(SE "$L" rs_effective_state alpha poolA)"
assert_eq "evidence: the success counter advanced to 1" "1" "$(SE "$L" rs_probe_evidence alpha | cut -f1)"
assert_eq "evidence: healthy_since stays unset below threshold" "-" \
    "$(SE "$L" rs_probe_evidence alpha | cut -f2)"
S "$L" rs_probe_pass pp2 alpha 2 >/dev/null 2>&1
assert_eq "evidence: reaching the threshold enters healthy" "healthy" \
    "$(SE "$L" rs_effective_state alpha poolA)"
assert "evidence: healthy_since is stamped at promotion" \
    bash -c "[[ \"\$(CCT_ROUTING_STATE='$L' bash -c \"source '$SLIB'; rs_probe_evidence alpha\" | cut -f2)\" =~ ^[0-9]+$ ]]"
assert "evidence: the promotion reason names the verified count" \
    bash -c "jq -e '.profiles.alpha.reason | test(\"probe-verified healthy\")' '$L'"

S "$L" rs_probe_fail pf1 alpha $((NOW + 600)) "canary returned 500" >/dev/null 2>&1
assert_eq "evidence: a failed probe resets the streak to 0" "0" "$(SE "$L" rs_probe_evidence alpha | cut -f1)"
assert_eq "evidence: a failed probe cools the profile" "cooldown" "$(SE "$L" rs_effective_state alpha poolA)"
assert_eq "evidence: healthy_since is cleared on failure" "-" "$(SE "$L" rs_probe_evidence alpha | cut -f2)"

# ── the threshold-crossing timestamp (review round 1): healthy_since
# must be the instant the STREAK CROSSED the threshold, not the first
# success — otherwise the dwell hysteresis is partly pre-satisfied.
TC="$TMP/cross.json"
S "$TC" rs_probe_begin tc0 kappa 1 >/dev/null 2>&1
S "$TC" rs_probe_pass tc1 kappa 2 >/dev/null 2>&1
assert_eq "crossing: first success stamps NO healthy_since" "-" \
    "$(SE "$TC" rs_probe_evidence kappa | cut -f2)"
FIRST=$(date -u +%s)
sleep 2
S "$TC" rs_probe_pass tc2 kappa 2 >/dev/null 2>&1
CROSS=$(SE "$TC" rs_probe_evidence kappa | cut -f2)
assert_eq "crossing: healthy_since is stamped at the CROSSING probe, not the first" "yes" \
    "$( [[ "$CROSS" -ge "$FIRST" ]] && echo yes || echo no )"
assert_eq "crossing: the profile is healthy only after the crossing" "healthy" \
    "$(SE "$TC" rs_effective_state kappa poolK)"

echo ""
echo "== T1.3: probe-QUALIFIED health (the failback predicate) =="

# B execution-evidence health is NOT probe-verified health
Q="$TMP/qual.json"
S "$Q" rs_mark_success q1 lambda >/dev/null 2>&1
assert_eq "execution evidence: rs_mark_success still records B healthy" "healthy" \
    "$(SE "$Q" rs_effective_state lambda poolL)"
assert_eq "execution evidence: it stamps NO healthy_since" "-" \
    "$(SE "$Q" rs_probe_evidence lambda | cut -f2)"
assert_eq "execution evidence: it touches NO probe counters" "0" \
    "$(SE "$Q" rs_probe_evidence lambda | cut -f1)"
assert "execution evidence: attempt-success health is NOT failback-qualified" \
    bash -c "! CCT_ROUTING_STATE='$Q' bash -c \"source '$SLIB'; rs_probe_qualified lambda 2\""
assert "probe-verified health IS failback-qualified at the threshold" \
    bash -c "CCT_ROUTING_STATE='$TC' bash -c \"source '$SLIB'; rs_probe_qualified kappa 2\""
assert "probe-verified health is NOT qualified against a HIGHER threshold" \
    bash -c "! CCT_ROUTING_STATE='$TC' bash -c \"source '$SLIB'; rs_probe_qualified kappa 3\""
assert "a below-threshold streak is never qualified" \
    bash -c "CCT_ROUTING_STATE='$TMP/q2.json' bash -c \"source '$SLIB'
        rs_probe_begin qb1 mu 1 >/dev/null 2>&1
        rs_probe_pass qp1 mu 2 >/dev/null 2>&1
        ! rs_probe_qualified mu 2\""

echo ""
echo "== T1.4: abandoned probes are ABSENCE of evidence =="

A="$TMP/abandon.json"
S "$A" rs_probe_begin ab-b1 gamma 1 >/dev/null 2>&1
S "$A" rs_probe_pass ab-p1 gamma 3 >/dev/null 2>&1   # one real success on record
S "$A" rs_probe_begin ab-b2 gamma 2 >/dev/null 2>&1
python3 - "$A" "$NOW" <<'PYEOF'
import json, sys
p, now = sys.argv[1], int(sys.argv[2])
d = json.load(open(p))
d["profiles"]["gamma"]["probe_started_at"] = now - 5000   # older than the abandon window
json.dump(d, open(p, "w"))
PYEOF
assert_eq "abandoned: an overdue in-flight marker reads as unknown" "unknown" \
    "$(SE "$A" rs_effective_state gamma poolG)"
assert_eq "abandoned: it is NEVER read as healthy" "no" \
    "$( [[ "$(SE "$A" rs_effective_state gamma poolG)" == "healthy" ]] && echo yes || echo no )"
assert_eq "abandoned: it is NEVER read as a failure/cooldown" "no" \
    "$( [[ "$(SE "$A" rs_effective_state gamma poolG)" == "cooldown" ]] && echo yes || echo no )"
assert_eq "abandoned: the success streak is UNCHANGED (no provider evidence inferred)" "1" \
    "$(SE "$A" rs_probe_evidence gamma | cut -f1)"
assert_eq "abandoned: the due query surfaces it for reconciliation" "gamma" \
    "$(SE "$A" rs_due_probes "$NOW")"

S "$A" rs_probe_abandon ab1 gamma $((NOW + 300)) >/dev/null 2>&1
assert_eq "abandon: the recorded state is unknown, not probe_fail" "unknown" \
    "$(SE "$A" rs_effective_state gamma poolG)"
assert_eq "abandon: counters STILL unchanged after the explicit transition" "1" \
    "$(SE "$A" rs_probe_evidence gamma | cut -f1)"
assert_eq "abandon: next_probe_at advanced" "$((NOW + 300))" \
    "$(SE "$A" rs_probe_evidence gamma | cut -f3)"
assert "abandon: the reason names absence of evidence" \
    bash -c "jq -e '.profiles.gamma.reason | test(\"no provider evidence inferred\")' '$A'"
assert "abandon: the in-flight generation is cleared" \
    bash -c "[[ \"\$(CCT_ROUTING_STATE='$A' bash -c \"source '$SLIB'; rs_probe_evidence gamma\" | cut -f4)\" == '-' ]]"

# a FRESH in-flight marker is not abandoned — the window matters
F="$TMP/fresh.json"
S "$F" rs_probe_begin fr1 delta 9 >/dev/null 2>&1
assert_eq "fresh in-flight: still reads as probing (not abandoned)" "probing" \
    "$(SE "$F" rs_effective_state delta poolD)"

echo ""
echo "== T1.5: health has a shelf life; decay never invents health =="

H="$TMP/ttl.json"
S "$H" rs_probe_begin h1 eps 1 >/dev/null 2>&1
S "$H" rs_probe_pass h2 eps 1 >/dev/null 2>&1
assert_eq "dwell: a fresh probe-verified profile is healthy" "healthy" \
    "$(SE "$H" rs_effective_state eps poolE)"
assert_eq "dwell: health older than the TTL decays to unknown" "unknown" \
    "$( ( set +e; CCT_ROUTING_STATE="$H" CCT_ROUTING_HEALTHY_TTL_SEC=0 source "$SLIB"; rs_effective_state eps poolE ) 2>/dev/null )"
assert_eq "decay: B's cooldown expiry still lands on unknown, never healthy" "unknown" \
    "$( S "$TMP/decay.json" rs_set_profile d1 zeta cooldown quota $((NOW - 5)) >/dev/null 2>&1; SE "$TMP/decay.json" rs_effective_state zeta poolZ )"
assert_eq "disabled: auth-disabled never decays on its own" "disabled" \
    "$( S "$TMP/dis.json" rs_set_profile x1 eta disabled auth - >/dev/null 2>&1; SE "$TMP/dis.json" rs_effective_state eta poolH )"

echo ""
echo "== T1.6: recovery timing precedence =="

pick() { R rd_next_probe_at "$NOW" alpha "${2:-3}" "$1" | cut -f2; }
inst() { R rd_next_probe_at "$NOW" alpha "${2:-3}" "$1" | cut -f1; }
assert_eq "precedence 1: provider reset_at wins" "reset_at" \
    "$(pick '{"reset_at":"2099-01-01T00:00:00Z","retry_after_sec":45,"rate_limits_resets_at":"2099-06-01T00:00:00Z"}')"
assert_eq "precedence 2: Retry-After when no reset_at" "retry_after" \
    "$(pick '{"retry_after_sec":45,"rate_limits_resets_at":"2099-06-01T00:00:00Z"}')"
assert_eq "precedence 3: rate_limits when neither" "rate_limits" \
    "$(pick '{"rate_limits_resets_at":"2099-06-01T00:00:00Z"}')"
assert_eq "precedence 4: bounded backoff as the LAST resort" "backoff" "$(pick '{}')"
assert_eq "precedence: a PAST reset_at falls through (never schedules in the past)" "backoff" \
    "$(pick '{"reset_at":"2001-01-01T00:00:00Z"}')"
assert_eq "precedence: malformed evidence falls through to backoff" "backoff" "$(pick 'not-json')"
assert_eq "Retry-After computes now+seconds exactly" "$((NOW + 45))" "$(inst '{"retry_after_sec":45}')"
assert "the backoff detail journals the named defaults" \
    bash -c "source '$RLIB'; rd_next_probe_at $NOW alpha 3 '{}' | grep -q 'RD_BACKOFF_BASE_SEC=60'"
assert_eq "source vocabulary is closed" "yes" \
    "$(bash -c "source '$RLIB'; rd_source_valid backoff && ! rd_source_valid guess && echo yes")"

assert_eq "backoff: bounded exponential windows" "60 120 240 480 960 1920" \
    "$(bash -c "source '$RLIB'; for i in 1 2 3 4 5 6; do printf '%s ' \$(rd_backoff_window \$i); done" | sed 's/ $//')"
assert_eq "backoff: the window is capped at RD_BACKOFF_MAX_SEC" "3600" \
    "$(bash -c "source '$RLIB'; rd_backoff_window 99")"
assert_eq "jitter: deterministic — identical inputs give an identical instant" "same" \
    "$( [[ "$(inst '{}')" == "$(inst '{}')" ]] && echo same || echo different )"
assert_eq "jitter: different failure counts give different instants" "different" \
    "$( [[ "$(inst '{}' 3)" == "$(inst '{}' 4)" ]] && echo same || echo different )"
assert "jitter: the offset stays within ±RD_JITTER_PCT of the window" \
    bash -c "source '$RLIB'; o=\$(rd_jitter_offset alpha 3 1000); [[ \${o#-} -le 200 ]]"
assert_eq "jitter: profile identity changes the instant (no thundering herd)" "different" \
    "$( a=$(R rd_next_probe_at "$NOW" alpha 3 '{}' | cut -f1); b=$(R rd_next_probe_at "$NOW" beta 3 '{}' | cut -f1); [[ "$a" == "$b" ]] && echo same || echo different )"
assert "iso conversion is host-portable (macOS + GNU)" \
    bash -c "source '$RLIB'; [[ \$(rd_iso_to_epoch '2099-01-01T00:00:00Z') == '4070908800' ]]"

echo ""
echo "== T1.7: increment-B compatibility =="

B="$TMP/bcompat.json"
S "$B" rs_set_profile b1 alpha cooldown "rate" $((NOW + 900)) >/dev/null 2>&1
S "$B" rs_set_pool b2 poolA cooldown "quota" $((NOW + 1800)) >/dev/null 2>&1
assert_eq "B: pool still outranks profile" "pool:cooldown" "$(SE "$B" rs_effective_state alpha poolA)"
assert_eq "B: rs_effective_info still returns state + until" "pool:cooldown	$((NOW + 1800))" \
    "$(SE "$B" rs_effective_info alpha poolA)"
assert_eq "B: rs_mark_success still records health from a real attempt" "healthy" \
    "$( S "$TMP/succ.json" rs_mark_success m1 theta >/dev/null 2>&1; SE "$TMP/succ.json" rs_effective_state theta poolT )"
assert "B: a pre-D store (no probe fields) reads without error" \
    bash -c "printf '%s' '{\"schema_version\":1,\"profiles\":{\"old\":{\"state\":\"cooldown\",\"reason\":\"r\",\"until\":null}},\"pools\":{},\"applied\":{}}' > '$TMP/pre-d.json'; CCT_ROUTING_STATE='$TMP/pre-d.json' bash -c \"source '$SLIB'; rs_effective_state old poolX\" | grep -qx cooldown"
assert_eq "B: a pre-D store reports zero probe evidence (absence, not error)" "0	-	-	-" \
    "$(SE "$TMP/pre-d.json" rs_probe_evidence old)"
assert "B: fail-closed reads unchanged (corrupt store still refuses)" \
    bash -c "printf 'garbage' > '$TMP/corrupt.json'; ! CCT_ROUTING_STATE='$TMP/corrupt.json' bash -c \"source '$SLIB'; rs_read\" 2>/dev/null"
assert "B: idempotency unchanged (a replayed attempt id is a no-op)" \
    bash -c "CCT_ROUTING_STATE='$TMP/idem.json' bash -c \"source '$SLIB'
        rs_set_profile same iota cooldown first $((NOW + 100)) >/dev/null 2>&1
        rs_set_profile same iota cooldown second $((NOW + 200)) >/dev/null 2>&1\"
        jq -e '.profiles.iota.reason == \"first\"' '$TMP/idem.json'"

echo ""
echo "== T2: the probe engine (canaries, accounting, taint) =="

PLIB="$REPO_DIR/scripts/lib/routing-probe.sh"
PT="$TMP/probe"; mkdir -p "$PT"
PJ_TOOL='{"id":"alpha","backend":"claude-code","model":"sonnet","tool_profile":"full-cct","credential_ref":"env:PROBE_KEY","endpoint_ref":"none"}'
PJ_CHAT='{"id":"beta","backend":"pi","model":"qwen","tool_profile":"chat-only","credential_ref":"none","endpoint_ref":"none"}'

# mock canary: $1 is the body run in place of the real backend command
mock() { printf '#!/usr/bin/env bash\ncat > /dev/null\n%s\n' "$1" > "$PT/mock.sh"; chmod +x "$PT/mock.sh"; }
# P <ledger> <profile-json> <generation> [env assignments...] -> "outcome\tdetail"
P() {
    local led="$1" pj="$2" gen="$3"; shift 3
    ( set +e
      export CCT_ROUTING_PROBE_LEDGER="$led" CCT_ROUTING_PROBE_CMD="bash $PT/mock.sh"
      [[ $# -gt 0 ]] && export "$@"
      source "$PLIB"; rb_probe "$pj" "$gen" 2>/dev/null )
}
PFULL() {  # same, but keeps RB_* globals by echoing extra fields
    local led="$1" pj="$2" gen="$3"; shift 3
    ( set +e
      export CCT_ROUTING_PROBE_LEDGER="$led" CCT_ROUTING_PROBE_CMD="bash $PT/mock.sh"
      [[ $# -gt 0 ]] && export "$@"
      source "$PLIB"; rb_probe "$pj" "$gen" >/dev/null 2>&1
      printf '%s|%s|%s\n' "$RB_OUTCOME" "$RB_COST" "$RB_TRANSCRIPT" )
}

assert_eq "outcome vocabulary is closed (four members)" "4" \
    "$(bash -c "source '$PLIB'; printf '%s\n' \$RB_OUTCOMES | wc -l | tr -d ' '")"
assert "outcome vocabulary rejects an unlisted outcome" \
    bash -c "source '$PLIB'; ! rb_outcome_valid probe_maybe"
assert "tool-profile map is closed (full-cct implies tools)" \
    bash -c "source '$PLIB'; rb_tools_implied full-cct && ! rb_tools_implied chat-only"

# ── real-canary contract
L1="$PT/l1.json"
mock 'printf CCT_TOOL_OK > "$CCT_PROBE_TOOL_FILE"; echo "{\"result\":\"CCT_PROBE_OK\",\"total_cost_usd\":0.011}"'
assert_eq "canary: inference + tool markers => probe_pass" "probe_pass" "$(P "$L1" "$PJ_TOOL" 1 | cut -f1)"
assert "canary: the pass detail names BOTH verifications" \
    grep -q "real inference verified + tool canary verified" <<< "$(P "$L1" "$PJ_TOOL" 11)"
mock 'echo "{\"result\":\"CCT_PROBE_OK\",\"total_cost_usd\":0.01}"'
assert_eq "canary: a tool-profiled builder answering inference ONLY => probe_fail" "probe_fail" \
    "$(P "$L1" "$PJ_TOOL" 2 | cut -f1)"
assert "canary: that failure names the tool-canary requirement" \
    grep -q "not healthy on inference alone" <<< "$(P "$L1" "$PJ_TOOL" 21)"
assert_eq "canary: the SAME output on a non-tool profile => probe_pass" "probe_pass" \
    "$(P "$L1" "$PJ_CHAT" 3 | cut -f1)"

# ── evidence honesty
mock 'echo "Error: 429 rate_limit_error"; exit 1'
assert_eq "evidence: a CLASSIFIABLE provider failure => probe_fail" "probe_fail" \
    "$(P "$L1" "$PJ_CHAT" 4 | cut -f1)"
assert "evidence: the failure names the classified cause" \
    grep -q "classified provider failure: rate_limited" <<< "$(P "$L1" "$PJ_CHAT" 41)"
mock 'echo "???"; exit 3'
assert_eq "evidence: unparseable output => probe_unverifiable, NEVER probe_fail" "probe_unverifiable" \
    "$(P "$L1" "$PJ_CHAT" 5 | cut -f1)"
assert "evidence: the unverifiable detail refuses to invent provider failure" \
    grep -q "never recorded as provider failure" <<< "$(P "$L1" "$PJ_CHAT" 51)"
mock 'exit 124'
assert_eq "evidence: a cut-off canary => probe_unverifiable (absence of evidence)" "probe_unverifiable" \
    "$(P "$L1" "$PJ_CHAT" 6 | cut -f1)"
assert "evidence: the cut-off detail says a missing answer is not failure" \
    grep -q "a missing answer is not provider failure" <<< "$(P "$L1" "$PJ_CHAT" 61)"
mock 'echo "command not found"; exit 127'
assert_eq "evidence: an absent backend => probe_unverifiable" "probe_unverifiable" \
    "$(P "$L1" "$PJ_CHAT" 7 | cut -f1)"

# ── accounting: launched implies accounted
L2="$PT/l2.json"
mock 'echo "unparseable garbage"; exit 9'
P "$L2" "$PJ_CHAT" 100 >/dev/null
assert_eq "accounting: a MALFORMED-evidence probe is still costed" "1" \
    "$(jq '[.probes[] | select(.generation == 100)] | length' "$L2")"
assert_eq "accounting: the unmeasurable cost uses the named estimate, flagged" "0.02 true" \
    "$(jq -r '.probes[] | select(.generation == 100) | "\(.cost_usd) \(.estimated)"' "$L2")"
mock 'exit 124'
P "$L2" "$PJ_CHAT" 101 >/dev/null
assert_eq "accounting: a TIMED-OUT probe is still costed" "1" \
    "$(jq '[.probes[] | select(.generation == 101)] | length' "$L2")"
mock 'echo "{\"result\":\"CCT_PROBE_OK\",\"total_cost_usd\":0.075}"'
P "$L2" "$PJ_CHAT" 102 >/dev/null
assert_eq "accounting: a measured cost REPLACES the estimate (no double count)" "1 0.075 false" \
    "$(jq -r '[.probes[] | select(.generation == 102)] | "\(length) \(.[0].cost_usd) \(.[0].estimated)"' "$L2")"
assert_eq "accounting: every launch left exactly one ledger row" "3" "$(jq '.probes | length' "$L2")"

# ── CRASH ACCOUNTING (review round 1): the reservation must be
# durable BEFORE the child can consume provider cost. Kill the prober
# after the child provably reached execution and inspect the ledger.
CRASH_LED="$PT/crash.json"
rm -f "$PT/launch-marker.txt"
printf '#!/usr/bin/env bash\ncat > /dev/null\necho LAUNCHED > "%s/launch-marker.txt"\nsleep 30\necho CCT_PROBE_OK\n' "$PT" > "$PT/mock.sh"
chmod +x "$PT/mock.sh"
( export CCT_ROUTING_PROBE_LEDGER="$CRASH_LED" CCT_ROUTING_PROBE_CMD="bash $PT/mock.sh"
  source "$PLIB"; rb_probe "$PJ_CHAT" 400 >/dev/null 2>&1 ) &
CRASH_PID=$!
for _ in $(seq 1 100); do [[ -f "$PT/launch-marker.txt" ]] && break; sleep 0.1; done
kill -9 "$CRASH_PID" 2>/dev/null || true
pkill -f "$PT/mock.sh" 2>/dev/null || true
wait "$CRASH_PID" 2>/dev/null || true
assert "crash: the child provably reached execution (provider cost was possible)" \
    bash -c "[[ -f '$PT/launch-marker.txt' ]]"
assert_eq "crash: the prober died BEFORE classification (no outcome recorded)" "no" \
    "$( [[ -f "$PT/crash-outcome.txt" ]] && echo yes || echo no )"
assert_eq "crash: EXACTLY ONE accounting row exists for the killed generation" "1" \
    "$(jq '[.probes[] | select(.generation == 400)] | length' "$CRASH_LED" 2>/dev/null || echo 0)"
assert_eq "crash: that row is the conservative ESTIMATE (reserved pre-launch)" "true" \
    "$(jq -r '.probes[] | select(.generation == 400) | .estimated' "$CRASH_LED" 2>/dev/null)"
assert_eq "crash: the estimate is the named default, never zero" "0.02" \
    "$(jq -r '.probes[] | select(.generation == 400) | .cost_usd' "$CRASH_LED" 2>/dev/null)"
assert "crash: no provider-health evidence was fabricated (the lib writes no circuit state)" \
    bash -c "! grep -q 'rs_probe_fail\|rs_probe_pass' '$PLIB'"

# ── caps admission: no launch, no fabricated result
L3="$PT/l3.json"
mock 'echo RAN > "'"$PT"'/ran-marker.txt"; echo CCT_PROBE_OK'
rm -f "$PT/ran-marker.txt"
printf '{"schema_version":1,"probes":[{"profile":"x","generation":1,"cost_usd":0.01,"estimated":false,"at":%s}]}' "$NOW" > "$L3"
CAP=$(P "$L3" "$PJ_CHAT" 200 RB_MAX_PROBES_PER_WINDOW=1)
assert_eq "caps: a blocking count cap yields probe_deferred_caps" "probe_deferred_caps" "$(cut -f1 <<< "$CAP")"
assert "caps: the deferral names the cap and says it did not launch" \
    bash -c "grep -q 'not launched' <<< \"\$0\" && grep -q 'RB_MAX_PROBES_PER_WINDOW' <<< \"\$0\"" "$CAP"
assert "caps: the child NEVER ran" bash -c "[[ ! -f '$PT/ran-marker.txt' ]]"
assert_eq "caps: a deferred probe is NOT debited (nothing was launched)" "1" "$(jq '.probes | length' "$L3")"
printf '{"schema_version":1,"probes":[{"profile":"x","generation":1,"cost_usd":9.99,"estimated":false,"at":%s}]}' "$NOW" > "$L3"
assert_eq "caps: a blocking COST cap also defers" "probe_deferred_caps" \
    "$(P "$L3" "$PJ_CHAT" 201 | cut -f1)"
printf '{"schema_version":1,"probes":[{"profile":"x","generation":1,"cost_usd":9.99,"estimated":false,"at":%s}]}' "$((NOW - 200000))" > "$L3"
assert_eq "caps: spend OUTSIDE the window does not block" "probe_pass" \
    "$(P "$L3" "$PJ_CHAT" 202 | cut -f1)"
printf 'garbage' > "$PT/bad.json"
CORRUPT=$(P "$PT/bad.json" "$PJ_CHAT" 250)
assert_eq "caps: corrupt accounting refuses to launch (admission, not evidence)" "probe_deferred_caps" \
    "$(cut -f1 <<< "$CORRUPT")"
assert "caps: the refusal names unaccountable probing" \
    grep -q "refusing to launch an unaccountable probe" <<< "$CORRUPT"

# ── secret taint: the value must be absent from EVERY probe surface
L4="$PT/l4.json"
mock 'echo "leaking $ANTHROPIC_API_KEY into stdout"; printf CCT_TOOL_OK > "$CCT_PROBE_TOOL_FILE"; echo CCT_PROBE_OK'
RES=$(PFULL "$L4" "$PJ_TOOL" 300 PROBE_KEY=super-secret-probe-value-77)
TRANS=$(cut -d'|' -f3 <<< "$RES")
assert_eq "taint: the probe still passes with a leaky child" "probe_pass" "$(cut -d'|' -f1 <<< "$RES")"
assert_eq "taint: the credential value is ABSENT from the persisted transcript" "0" \
    "$(grep -c 'super-secret-probe-value-77' "$TRANS" 2>/dev/null | head -1)"
assert "taint: the transcript shows the redaction marker instead" \
    grep -q 'REDACTED:ANTHROPIC_API_KEY' "$TRANS"
assert_eq "taint: the credential value is ABSENT from the accounting ledger" "0" \
    "$(grep -c 'super-secret-probe-value-77' "$L4" 2>/dev/null | head -1)"
assert_eq "taint: the credential value is ABSENT from every probe artifact" "0" \
    "$(grep -rl 'super-secret-probe-value-77' "$(dirname "$TRANS")" 2>/dev/null | grep -v capture.log | wc -l | tr -d ' ')"
assert "taint: the child received NO cost-file or ledger capability" \
    bash -c "! grep -q 'CCT_ROUTING_PROBE_LEDGER' '$PLIB' || ! grep -A3 'bash -c \"\$cmd\"' '$PLIB' | grep -q LEDGER"

echo ""
echo "========================================="
echo "  routing-recovery tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_RECOVERY_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_RECOVERY_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
