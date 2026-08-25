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
SELECT_LIB="$REPO_DIR/scripts/lib/routing-select.sh"
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

# The state reader deliberately surfaces D's marker states so callers
# can explain them. That does not make them selectable: B's selector
# used a wildcard for every state other than cooldown/disabled, which
# would otherwise launch work while a probe was due, in flight, or had
# explicitly reported degradation.
SEL_EFF='{"enabled":true,"candidates":[["alpha","claude-code","provider","model","tier1",1,"poolA",["build"],"full-cct","approved-cloud","mode:login","none"]]}'
for marker in degraded probe_due probing; do
    SEL_STATE="$TMP/select-profile-$marker.json"
    jq -n --arg m "$marker" --argjson now "$NOW" \
        '{schema_version:1,profiles:{alpha:{state:$m,until:null,probe_started_at:$now}},pools:{},applied:{}}' > "$SEL_STATE"
    assert "selector: profile recovery marker '$marker' is NOT eligible" \
        env CCT_ROUTING_STATE="$SEL_STATE" SEL_EFF="$SEL_EFF" bash -c \
        'source "$1"; out=$(rt_select "$SEL_EFF" "[]" build); jq -e '\''(.selected == null) and (.considered[0].reason | contains("not selectable"))'\'' <<< "$out"' _ "$SELECT_LIB"

    SEL_POOL_STATE="$TMP/select-pool-$marker.json"
    jq -n --arg m "$marker" --argjson now "$NOW" \
        '{schema_version:1,profiles:{},pools:{poolA:{state:$m,until:null,probe_started_at:$now}},applied:{}}' > "$SEL_POOL_STATE"
    assert "selector: pool recovery marker '$marker' is NOT eligible" \
        env CCT_ROUTING_STATE="$SEL_POOL_STATE" SEL_EFF="$SEL_EFF" bash -c \
        'source "$1"; out=$(rt_select "$SEL_EFF" "[]" build); jq -e '\''(.selected == null) and (.considered[0].reason | contains("not selectable"))'\'' <<< "$out"' _ "$SELECT_LIB"
done

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
assert "evidence: a below-threshold pass stays due for the next scheduler tick" \
    bash -c "N=\$(date -u +%s); D=\$(CCT_ROUTING_STATE='$L' bash -c \"source '$SLIB'; rs_probe_evidence alpha\" | cut -f3); [[ \$D =~ ^[0-9]+$ && \$D -le \$N ]]"
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
jq --argjson due "$((NOW - 1))" '.profiles.alpha.next_probe_at = $due | .profiles.alpha.until = $due' \
    "$L" > "$TMP/life-due.json"
assert_eq "evidence: an expired D cooldown reads probe_due until the canary runs" "probe_due" \
    "$(SE "$TMP/life-due.json" rs_effective_state alpha poolA)"

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

# mock canary: $1 is the body run in place of the real backend command.
# A passing mock must derive the run-specific expected response from the
# prompt; a fixed marker can no longer prove inference.
mock() {
    printf '#!/usr/bin/env bash\nPROMPT=$(cat)\nEXPECTED=$(printf "%%s\\n" "$PROMPT" | grep -oE "CCT_PROBE_OK:[0-9a-f]{20}" | tail -1)\n%s\n' "$1" > "$PT/mock.sh"
    chmod +x "$PT/mock.sh"
}
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
      source "$PLIB"
      rb_probe_cleanup() {
          cp "$1/capture.log" "$PT/pfull-capture.log" 2>/dev/null || true
          rm -rf "$1" 2>/dev/null || true
          RB_TRANSCRIPT="$PT/pfull-capture.log"
      }
      rb_probe "$pj" "$gen" >/dev/null 2>&1
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
mock 'printf CCT_TOOL_OK > "$CCT_PROBE_TOOL_FILE"; printf "{\"result\":\"%s\",\"total_cost_usd\":0.011}\\n" "$EXPECTED"'
assert_eq "canary: inference + tool markers => probe_pass" "probe_pass" "$(P "$L1" "$PJ_TOOL" 1 | cut -f1)"
assert "canary: the pass detail names BOTH verifications" \
    grep -q "real inference verified + tool canary verified" <<< "$(P "$L1" "$PJ_TOOL" 11)"
mock 'printf "{\"result\":\"%s\",\"total_cost_usd\":0.01}\\n" "$EXPECTED"'
assert_eq "canary: a tool-profiled builder answering inference ONLY => probe_fail" "probe_fail" \
    "$(P "$L1" "$PJ_TOOL" 2 | cut -f1)"
assert "canary: that failure names the tool-canary requirement" \
    grep -q "not healthy on inference alone" <<< "$(P "$L1" "$PJ_TOOL" 21)"
assert_eq "canary: the SAME output on a non-tool profile => probe_pass" "probe_pass" \
    "$(P "$L1" "$PJ_CHAT" 3 | cut -f1)"

# Echoing the prompt is not inference evidence. The run-specific marker is
# accepted only as the exact parsed backend result, never because it appears
# in a prompt/user/transcript field or on stderr.
mock 'printf "%s" "$PROMPT" | jq -Rs '\''{type:"result",result:.}'\'''
assert_eq "canary: a backend that only echoes its prompt cannot mint health" "probe_unverifiable" \
    "$(P "$L1" "$PJ_CHAT" 31 | cut -f1)"
mock 'printf "prompt was: %s\\n" "$PROMPT" >&2; echo "{\"type\":\"result\",\"result\":\"not the derived answer\"}"'
assert_eq "canary: a marker echoed on stderr cannot satisfy the parsed result" "probe_unverifiable" \
    "$(P "$L1" "$PJ_CHAT" 32 | cut -f1)"
mock 'printf "{\"type\":\"result\",\"result\":\"%s   \"}\\n" "$EXPECTED"'
assert_eq "canary: surrounding response whitespace does not suppress valid evidence" "probe_pass" \
    "$(P "$L1" "$PJ_CHAT" 34 | cut -f1)"
mock 'printf "backend notice: using cached credentials\\n"; printf "{\"type\":\"result\",\"result\":\"%s\",\"total_cost_usd\":0.031}\\n" "$EXPECTED"'
assert_eq "canary: a non-JSON notice cannot hide the structured result" "probe_pass" \
    "$(P "$L1" "$PJ_CHAT" 35 | cut -f1)"
assert_eq "accounting: a non-JSON notice cannot hide measured cost" "0.031 false" \
    "$(jq -r '.probes[] | select(.generation == 35) | "\(.cost_usd) \(.estimated)"' "$L1")"

# Probe sandboxes are ephemeral even on the success path.
mkdir -p "$PT/tmp-root"
mock 'printf "{\"result\":\"%s\"}\\n" "$EXPECTED"'
P "$L1" "$PJ_CHAT" 33 "TMPDIR=$PT/tmp-root" >/dev/null
assert_eq "sandbox: a completed probe leaves no private temp directory" "0" \
    "$(find "$PT/tmp-root" -maxdepth 1 -type d -name 'cct-probe.*' | wc -l | tr -d ' ')"

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

# The private execution root is safety scaffolding, not an optional
# convenience. If it cannot be created, no provider code runs and no
# reservation is charged for an invocation that never started.
REAL_MKTEMP=$(command -v mktemp)
mkdir -p "$PT/no-sandbox-bin"
printf '#!/usr/bin/env bash\nif [[ "${1:-}" == "-d" ]]; then exit 1; fi\nexec "%s" "$@"\n' "$REAL_MKTEMP" > "$PT/no-sandbox-bin/mktemp"
chmod +x "$PT/no-sandbox-bin/mktemp"
mock 'echo LAUNCHED > "'"$PT"'/sandbox-launch.txt"; echo CCT_PROBE_OK'
rm -f "$PT/sandbox-launch.txt" "$PT/no-sandbox-ledger.json"
NO_SANDBOX=$(PATH="$PT/no-sandbox-bin:$PATH" P "$PT/no-sandbox-ledger.json" "$PJ_CHAT" 8)
assert_eq "sandbox: setup failure is infrastructure-unverifiable" "probe_unverifiable" "$(cut -f1 <<< "$NO_SANDBOX")"
assert "sandbox: setup failure names the refused execution boundary" \
    grep -q "refusing to execute provider code" <<< "$NO_SANDBOX"
assert "sandbox: setup failure launches nothing and debits nothing" \
    bash -c "[[ ! -e '$PT/sandbox-launch.txt' && ! -e '$PT/no-sandbox-ledger.json' ]]"

mock 'echo LAUNCHED > "'"$PT"'/unlock-launch.txt"; echo CCT_PROBE_OK'
rm -f "$PT/unlock-launch.txt"
UNLOCK_FAIL=$( set +e
    export CCT_ROUTING_PROBE_LEDGER="$PT/unlock-ledger.json" CCT_ROUTING_PROBE_CMD="bash $PT/mock.sh"
    source "$PLIB"
    _rb_unlock() { return 1; }
    rb_probe "$PJ_CHAT" 9 2>/dev/null )
assert_eq "accounting lock: an unproven release is infrastructure-unverifiable" "probe_unverifiable" \
    "$(cut -f1 <<< "$UNLOCK_FAIL")"
assert "accounting lock: an unproven release launches nothing" \
    bash -c "[[ ! -e '$PT/unlock-launch.txt' ]]"

# A dead PID does not make check-then-delete safe: a replacement writer
# can acquire between those operations. Accounting fails closed and
# leaves the existing lock for explicit operator recovery.
DEAD_LOCK_PID=$(bash -c 'echo $$')
while kill -0 "$DEAD_LOCK_PID" 2>/dev/null; do DEAD_LOCK_PID=$((DEAD_LOCK_PID + 1)); done
mkdir -p "$PT/dead-lock-ledger.json.lock"
printf '%s\n' "$DEAD_LOCK_PID" > "$PT/dead-lock-ledger.json.lock/pid"
DEAD_LOCK_OUT=$( set +e
    export CCT_ROUTING_PROBE_LEDGER="$PT/dead-lock-ledger.json" RB_LOCK_WAIT_SEC=1
    source "$PLIB"
    rb_reserve alpha 10 )
assert "accounting lock: a dead recorded owner still fails closed" \
    grep -q "accounting lock unavailable" <<< "$DEAD_LOCK_OUT"
assert_eq "accounting lock: refusal never deletes a possible replacement lock" "$DEAD_LOCK_PID" \
    "$(cat "$PT/dead-lock-ledger.json.lock/pid")"

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
mock 'printf "{\"result\":\"%s\",\"total_cost_usd\":0.075}\\n" "$EXPECTED"'
P "$L2" "$PJ_CHAT" 102 >/dev/null
assert_eq "accounting: a measured cost REPLACES the estimate (no double count)" "1 0.075 false" \
    "$(jq -r '[.probes[] | select(.generation == 102)] | "\(length) \(.[0].cost_usd) \(.[0].estimated)"' "$L2")"
assert_eq "accounting: every launch left exactly one ledger row" "3" "$(jq '.probes | length' "$L2")"

mock 'printf "{\"type\":\"result\",\"result\":\"%s\",\"total_cost_usd\":\"1.2.3\"}\\n" "$EXPECTED"'
assert_eq "accounting: malformed cost text cannot discard a genuine pass" "probe_pass" \
    "$(P "$L2" "$PJ_CHAT" 105 | cut -f1)"
assert_eq "accounting: malformed cost keeps the conservative estimate" "0.02 true" \
    "$(jq -r '.probes[] | select(.generation == 105) | "\(.cost_usd) \(.estimated)"' "$L2")"

# The probe's child environment must never be implemented by mutating
# the caller shell. In particular, the post-execution refusal used to
# return before its cleanup and leave the profile credential exported.
ENV_LED="$PT/env-scope.json"
mock 'rm -f "'"$ENV_LED"'"; echo CCT_PROBE_OK'
ENV_SCOPE=$( set +e
    export CCT_ROUTING_PROBE_LEDGER="$ENV_LED" CCT_ROUTING_PROBE_CMD="bash $PT/mock.sh"
    export PROBE_KEY="profile-secret" ANTHROPIC_API_KEY="caller-api" ANTHROPIC_BASE_URL="https://caller.invalid"
    source "$PLIB"
    rb_probe "$PJ_TOOL" 103 >/dev/null 2>&1
    printf '%s|%s|%s\n' "$RB_OUTCOME" "${ANTHROPIC_API_KEY-<unset>}" "${ANTHROPIC_BASE_URL-<unset>}" )
assert_eq "child env: a vanished reservation is unverifiable" "probe_unverifiable" \
    "$(cut -d'|' -f1 <<< "$ENV_SCOPE")"
assert_eq "child env: every return path preserves the caller's credential and endpoint variables" \
    "caller-api|https://caller.invalid" "$(cut -d'|' -f2- <<< "$ENV_SCOPE")"

mock 'printf "{\"result\":\"%s\",\"total_cost_usd\":0.075}\\n" "$EXPECTED"'
MEASURE_FAIL=$( set +e
    export CCT_ROUTING_PROBE_LEDGER="$PT/measure-fail.json" CCT_ROUTING_PROBE_CMD="bash $PT/mock.sh"
    source "$PLIB"
    rb_debit() { return 1; }
    rb_probe "$PJ_CHAT" 104 2>/dev/null )
assert_eq "accounting: a measured-cost publication failure cannot report probe_pass" "probe_unverifiable" \
    "$(cut -f1 <<< "$MEASURE_FAIL")"
assert "accounting: the refusal names spend that cannot be enforced" \
    grep -q "measured probe cost.*cannot be enforced" <<< "$MEASURE_FAIL"

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
mock 'echo RAN > "'"$PT"'/ran-marker.txt"; printf "{\"result\":\"%s\"}\\n" "$EXPECTED"'
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
printf '{"schema_version":1,"probes":[{"profile":"x","generation":1,"cost_usd":1.99,"estimated":false,"at":%s}]}' "$NOW" > "$L3"
EDGE=$(P "$L3" "$PJ_CHAT" 203 RB_MAX_PROBE_COST_USD=2.00 RB_ESTIMATE_USD=0.02)
assert_eq "caps: admission includes the pending estimate in the cost cap" "probe_deferred_caps" \
    "$(cut -f1 <<< "$EDGE")"
assert_eq "caps: a rejected reservation cannot push the ledger over its cap" "1.99" \
    "$(jq '[.probes[].cost_usd] | add' "$L3")"
printf '{"schema_version":1,"probes":[{"profile":"x","generation":1,"cost_usd":9.99,"estimated":false,"at":%s}]}' "$((NOW - 200000))" > "$L3"
assert_eq "caps: spend OUTSIDE the window does not block" "probe_pass" \
    "$(P "$L3" "$PJ_CHAT" 202 | cut -f1)"
printf 'garbage' > "$PT/bad.json"
CORRUPT=$(P "$PT/bad.json" "$PJ_CHAT" 250)
assert_eq "accounting: corrupt accounting is infrastructure-unverifiable, never a cap" "probe_unverifiable" \
    "$(cut -f1 <<< "$CORRUPT")"
assert "caps: the refusal names unaccountable probing" \
    grep -q "refusing to launch an unaccountable probe" <<< "$CORRUPT"

# ── secret taint: the value must be absent from EVERY probe surface
L4="$PT/l4.json"
mock 'ROOT="$(dirname "$CCT_PROBE_TOOL_FILE")/untrusted-routing"; if [[ "$CCT_ROUTING_PROBE_LEDGER" == "$ROOT/probe-ledger.json" && "$CCT_ROUTING_STATE" == "$ROOT/state.json" && "$CCT_ROUTING_TICK_LOCK" == "$ROOT/tick.lock" && "$CCT_ROUTING_REGISTRY" == "$ROOT/registry.toml" && "$CCT_SUPERVISOR_DIR" == "$ROOT/supervisor" && "$CCT_ROUTING_ARTIFACT_DIR" == "$ROOT/artifacts" ]]; then echo isolated; else printf "%s|%s|%s|%s|%s|%s\\n" "$CCT_ROUTING_PROBE_LEDGER" "$CCT_ROUTING_STATE" "$CCT_ROUTING_TICK_LOCK" "$CCT_ROUTING_REGISTRY" "$CCT_SUPERVISOR_DIR" "$CCT_ROUTING_ARTIFACT_DIR"; fi > "'"$PT"'/child-env.txt"; PARENT=$PPID; : > "'"$PT"'/ancestor-argv.txt"; I=0; while [[ "$PARENT" =~ ^[0-9]+$ && "$PARENT" -gt 1 && "$I" -lt 8 ]]; do ps -o command= -p "$PARENT" >> "'"$PT"'/ancestor-argv.txt" 2>/dev/null || true; PARENT=$(ps -o ppid= -p "$PARENT" 2>/dev/null | tr -d " "); I=$((I+1)); done; echo "leaking $ANTHROPIC_API_KEY into stdout" >&2; printf CCT_TOOL_OK > "$CCT_PROBE_TOOL_FILE"; printf "{\"result\":\"%s\"}\\n" "$EXPECTED"'
RES=$(PFULL "$L4" "$PJ_TOOL" 300 PROBE_KEY=super-secret-probe-value-77 \
    CCT_ROUTING_STATE=/private/state CCT_ROUTING_TICK_LOCK=/private/tick-lock \
    CCT_ROUTING_REGISTRY=/private/registry CCT_SUPERVISOR_DIR=/private/supervisor \
    CCT_ROUTING_ARTIFACT_DIR=/private/routing-artifacts)
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
assert_eq "taint: child routing libraries resolve only to private per-probe paths" \
    "isolated" "$(cat "$PT/child-env.txt")"
assert_eq "taint: the credential value is absent from the process argv chain" "0" \
    "$(grep -c 'super-secret-probe-value-77' "$PT/ancestor-argv.txt" 2>/dev/null || true)"

echo ""
# ── the probe time bound is ENFORCED, not merely declared ──
# A mock that exits 124 proves the classifier, not the bound. This
# hangs for real and must be cut off.
HANG="$TMP/hang"; mkdir -p "$HANG"
printf '#!/usr/bin/env bash\ncat > /dev/null\nsleep 30\necho CCT_PROBE_OK\n' > "$HANG/hang.sh"
chmod +x "$HANG/hang.sh"
HT0=$(date -u +%s)
HRES=$( set +e
    export CCT_ROUTING_PROBE_LEDGER="$HANG/led.json" CCT_ROUTING_PROBE_CMD="bash $HANG/hang.sh" RB_TIMEOUT_SEC=1
    source "$PLIB"
    rb_probe "$PJ_CHAT" 900 2>/dev/null )
HT1=$(date -u +%s)
assert_eq "bound: a HANGING provider is cut off, never left to run" "probe_unverifiable" \
    "$(cut -f1 <<< "$HRES")"
assert_eq "bound: ...within the bound plus the fixed KILL grace, not the provider's duration" "yes" \
    "$( [[ $((HT1 - HT0)) -le 10 ]] && echo yes || echo "no ($((HT1 - HT0))s)" )"
assert "bound: the detail names the bound that fired" \
    grep -q "cut off after 1s" <<< "$HRES"
assert_eq "bound: no descendant of the probe survives it" "0" \
    "$(pgrep -f "$HANG/hang.sh" 2>/dev/null | wc -l | tr -d ' ')"
assert "bound: a timeout is never a provider verdict" \
    grep -q "not provider failure" <<< "$HRES"
assert "bound: the probe runs through the shared bounded runner, not a second watchdog" \
    bash -c "grep -q 'ca_run_bounded \"\\\$RB_TIMEOUT_SEC\"' '$PLIB'"
HBAD=$( set +e
    export CCT_ROUTING_PROBE_LEDGER="$HANG/led2.json" CCT_ROUTING_PROBE_CMD="bash $HANG/hang.sh" RB_TIMEOUT_SEC=0
    source "$PLIB"
    rb_probe "$PJ_CHAT" 901 2>/dev/null )
assert_eq "bound: a non-positive bound REFUSES to launch rather than run unbounded" "probe_unverifiable" \
    "$(cut -f1 <<< "$HBAD")"
assert "bound: ...and says so by name" grep -q "refusing to run an unbounded probe" <<< "$HBAD"

# ── accounting survives CONCURRENT probes ──
# T3 releases the state lock before probing, so probes overlap by
# design. An unserialised read-modify-write silently drops rows, and a
# dropped row is a launched probe that went unaccounted.
CONC="$TMP/conc"; mkdir -p "$CONC"
printf '#!/usr/bin/env bash\nP=$(cat)\nE=$(printf "%%s\\n" "$P" | grep -oE "CCT_PROBE_OK:[0-9a-f]{20}" | tail -1)\nprintf "{\\"result\\":\\"%%s\\"}\\n" "$E"\n' > "$CONC/ok.sh"
chmod +x "$CONC/ok.sh"
for i in $(seq 1 20); do
    ( set +e
      export CCT_ROUTING_PROBE_LEDGER="$CONC/led.json" CCT_ROUTING_PROBE_CMD="bash $CONC/ok.sh"
      source "$PLIB"
      rb_probe "$PJ_CHAT" "$i" >/dev/null 2>&1 ) &
done
wait
assert_eq "accounting: 20 CONCURRENT probes leave 20 rows — no lost update" "20" \
    "$(jq '.probes | length' "$CONC/led.json")"
assert_eq "accounting: ...one row per generation, none merged or dropped" "20" \
    "$(jq '[.probes[].generation] | unique | length' "$CONC/led.json")"
assert "accounting: the debit is serialised without racy dead-owner deletion" \
    bash -c "body=\$(sed -n '/^_rb_lock()/,/^}/p' '$PLIB'); grep -q 'Do not reclaim by PID check' <<< \"\$body\" && ! grep -q 'kill -0' <<< \"\$body\""
assert "accounting: the lock leaves nothing behind" \
    bash -c "[[ ! -d '$CONC/led.json.lock' ]]"

echo "== T3: routing tick — due-only probing, idempotency, lock =="

CLI="$REPO_DIR/scripts/routing-cli.sh"
TK="$TMP/tick"; mkdir -p "$TK"
cat > "$TK/reg.toml" <<'REOF'
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
roles = ["build"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_env = "TICK_KEY"
base_url_env = "TICK_URL"
REOF
export TICK_KEY="tick-fixture-secret" TICK_URL="https://tick-fixture.invalid"
printf '#!/usr/bin/env bash\nP=$(cat)\nE=$(printf "%%s\\n" "$P" | grep -oE "CCT_PROBE_OK:[0-9a-f]{20}" | tail -1)\n[[ "${ANTHROPIC_API_KEY:-}" == tick-fixture-secret && "${ANTHROPIC_BASE_URL:-}" == https://tick-fixture.invalid ]] || { echo "profile wiring missing"; exit 1; }\nprintf CCT_TOOL_OK > "$CCT_PROBE_TOOL_FILE"\nprintf "{\\"result\\":\\"%%s\\"}\\n" "$E"\n' > "$TK/pass.sh"
printf '#!/usr/bin/env bash\ncat > /dev/null\necho "Error: 429 rate_limit_error"\nexit 1\n' > "$TK/fail.sh"
chmod +x "$TK/pass.sh" "$TK/fail.sh"
TSTATE="$TK/state.json"
TICK() {  # TICK <mock> [extra args...]
    local mock="$1"; shift
    ( set +e; cd "$REPO_DIR"
      CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$TSTATE" \
      CCT_ROUTING_PROBE_LEDGER="$TK/led.json" CCT_ROUTING_PROBE_CMD="bash $TK/$mock" \
      bash "$CLI" tick --due --once "$@" 2>/dev/null )
}
TS() { ( set +e; CCT_ROUTING_STATE="$TSTATE" source "$SLIB"; "$@" ) 2>/dev/null; }

printf '{"schema_version":1,"profiles":{},"pools":{},"applied":{}}' > "$TSTATE"
assert "tick: --due and --once are both required" \
    bash -c "cd '$REPO_DIR'; ! CCT_ROUTING_REGISTRY='$TK/reg.toml' CCT_ROUTING_STATE='$TSTATE' bash '$CLI' tick --due 2>/dev/null"
assert "tick: nothing due is a clean no-op" bash -c "TICKOUT=\$(cd '$REPO_DIR'; CCT_ROUTING_REGISTRY='$TK/reg.toml' CCT_ROUTING_STATE='$TSTATE' CCT_ROUTING_PROBE_CMD='bash $TK/pass.sh' bash '$CLI' tick --due --once 2>/dev/null); grep -q '0 due profile' <<< \"\$TICKOUT\""
cp "$TSTATE" "$TK/before.json"
TICK pass.sh >/dev/null
assert "tick: IDEMPOTENT — a second run with nothing due leaves state byte-identical" \
    cmp -s "$TSTATE" "$TK/before.json"

TS rs_schedule_probe s1 alpha "$((NOW - 5))" "reset reached" >/dev/null
OUT=$(TICK pass.sh)
assert "tick: a DUE profile is probed through its credential + endpoint refs" grep -q "alpha: probe_pass" <<< "$OUT"
assert_eq "tick: one pass below threshold does not reach healthy" "1" \
    "$(TS rs_probe_evidence alpha | cut -f1)"
TICK pass.sh >/dev/null
assert_eq "tick: the SECOND pass crosses the threshold into healthy" "healthy" \
    "$(TS rs_effective_state alpha poolA)"
assert "tick: the promoted profile is failback-qualified" \
    bash -c "CCT_ROUTING_STATE='$TSTATE' bash -c \"source '$SLIB'; rs_probe_qualified alpha 2\""

TS rs_schedule_probe s3 alpha "$((NOW - 5))" "recheck" >/dev/null
OUT=$(TICK fail.sh)
assert "tick: a classified failure records probe_fail with its next schedule" \
    grep -q "alpha: probe_fail" <<< "$OUT"
assert_eq "tick: the failure reset the streak" "0" "$(TS rs_probe_evidence alpha | cut -f1)"
assert_eq "tick: the first verified failure is recorded separately from the success streak" "1" \
    "$(TS rs_probe_failure_count alpha)"
TS rs_schedule_probe s3b alpha "$((NOW - 5))" "recheck again" >/dev/null
OUT=$(TICK fail.sh)
assert "tick: repeated verified failures advance exponential backoff" \
    grep -q "window 120s" <<< "$OUT"
assert_eq "tick: the verified failure streak reaches two" "2" \
    "$(TS rs_probe_failure_count alpha)"

# an UNVERIFIABLE probe must leave the state unknown — never cooled
# as though the provider had failed (the tick applies T2's evidence
# honesty through T1's primitives)
printf '#!/usr/bin/env bash\ncat > /dev/null\necho "???"\nexit 3\n' > "$TK/unver.sh"
chmod +x "$TK/unver.sh"
TS rs_probe_pass uv0 alpha 5 >/dev/null          # one real success on record
STREAK_BEFORE=$(TS rs_probe_evidence alpha | cut -f1)
TS rs_schedule_probe s4 alpha "$((NOW - 5))" "recheck" >/dev/null
OUT=$(TICK unver.sh)
assert "tick: an unverifiable probe is reported as such" \
    grep -q "alpha: probe_unverifiable" <<< "$OUT"
assert_eq "tick: an unverifiable probe leaves the state UNKNOWN, never cooled" "unknown" \
    "$(TS rs_effective_state alpha poolA)"
assert_eq "tick: an unverifiable probe leaves the success streak UNTOUCHED" "$STREAK_BEFORE" \
    "$(TS rs_probe_evidence alpha | cut -f1)"
assert "tick: the unverifiable detail says the state stays unknown" \
    grep -q "state stays unknown" <<< "$OUT"
UV_BACKOFF_1=$(TS rs_probe_backoff_count alpha)
UV_NEXT_1=$(jq -r '.profiles.alpha.next_probe_at' "$TSTATE")
UV_FAILURES=$(TS rs_probe_failure_count alpha)
TS rs_schedule_probe s4b alpha "$((NOW - 5))" "retry unverifiable" >/dev/null
TICK unver.sh >/dev/null
assert_eq "tick: unverifiable probes advance their own scheduling backoff" "$((UV_BACKOFF_1 + 1))" \
    "$(TS rs_probe_backoff_count alpha)"
assert "tick: repeated unverifiable probes move the next attempt farther out" \
    bash -c "[[ \$(jq -r '.profiles.alpha.next_probe_at' '$TSTATE') -gt '$UV_NEXT_1' ]]"
assert_eq "tick: unverifiable backoff never fabricates another provider failure" "$UV_FAILURES" \
    "$(TS rs_probe_failure_count alpha)"

# A cap refusal is also non-evidence, but it must advance scheduling
# backoff. Otherwise every short scheduler tick reclaims the same
# profile throughout the accounting window and contends on both locks.
CAP_BACKOFF_BEFORE=$(TS rs_probe_backoff_count alpha)
CAP_FAILURES_BEFORE=$(TS rs_probe_failure_count alpha)
TS rs_schedule_probe cap-due alpha "$((NOW - 5))" "retry after cap" >/dev/null
CAP_TICK=$( set +e; cd "$REPO_DIR"
    CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$TSTATE" \
    CCT_ROUTING_PROBE_LEDGER="$TK/capped-ledger.json" \
    CCT_ROUTING_PROBE_CMD="bash $TK/pass.sh" RB_MAX_PROBES_PER_WINDOW=0 \
    bash "$CLI" tick --due --once 2>/dev/null )
assert "tick: a capped probe is reported as deferred, not executed evidence" \
    grep -q "alpha: probe_deferred_caps" <<< "$CAP_TICK"
assert_eq "tick: cap deferral advances scheduling backoff" "$((CAP_BACKOFF_BEFORE + 1))" \
    "$(TS rs_probe_backoff_count alpha)"
assert_eq "tick: cap deferral never fabricates provider failure" "$CAP_FAILURES_BEFORE" \
    "$(TS rs_probe_failure_count alpha)"

# abandoned in-flight markers are reconciled FIRST and never as failure
TS rs_probe_begin ab1 alpha 4242 >/dev/null
python3 - "$TSTATE" "$NOW" <<'PYEOF2'
import json, sys
d = json.load(open(sys.argv[1]))
d["profiles"]["alpha"]["probe_started_at"] = int(sys.argv[2]) - 5000
json.dump(d, open(sys.argv[1], "w"))
PYEOF2
OUT=$(TICK pass.sh)
assert "tick: an abandoned in-flight marker is reconciled, not probed as failure" \
    grep -q "abandoned in-flight probe reconciled" <<< "$OUT"
assert "tick: the reconciliation names absence of provider evidence" \
    grep -q "no provider evidence inferred" <<< "$OUT"
assert_eq "tick: the abandoned reconciliation ran NO probe" "0" \
    "$(grep -c 'probe_pass' <<< "$OUT" || true)"

# The scheduler-wide lock covers the whole tick, not only a state write.
mkdir -p "$TSTATE.tick.lock"; echo $$ > "$TSTATE.tick.lock/pid"
TICK_LOCK_START=$(date -u +%s)
OUT=$( ( set +e; cd "$REPO_DIR"; CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$TSTATE" bash "$CLI" tick --due --once 2>&1 ) )
TICK_LOCK_ELAPSED=$(( $(date -u +%s) - TICK_LOCK_START ))
rm -rf "$TSTATE.tick.lock"
assert "tick: a concurrent scheduler is REFUSED by the global tick lock" \
    grep -q "another scheduler holds" <<< "$OUT"
assert_eq "tick: the global-lock refusal is IMMEDIATE" "yes" \
    "$( [[ "$TICK_LOCK_ELAPSED" -le 5 ]] && echo yes || echo no )"
assert "tick: release retains ownership state when the scheduler lock is no longer provably ours" \
    env CCT_ROUTING_STATE="$TSTATE" CCT_ROUTING_TICK_LOCK="$TK/owned.tick.lock" bash -c '
      source "$1"
      rs_tick_trylock
      printf 999999 > "$RS_TICK_LOCK/pid"
      ! rs_tick_unlock
      [[ "$RS_TICK_LOCK_HELD" == 1 && -d "$RS_TICK_LOCK" ]]
      printf %s "$$" > "$RS_TICK_LOCK/pid"
      rs_tick_unlock' _ "$SLIB"

# The new unattended lock paths never reclaim by PID liveness. A
# check-then-delete can remove a replacement acquired after the check.
DEAD_SCHED_PID=$(bash -c 'echo $$')
while kill -0 "$DEAD_SCHED_PID" 2>/dev/null; do DEAD_SCHED_PID=$((DEAD_SCHED_PID + 1)); done
mkdir -p "$TK/dead.tick.lock"
printf '%s\n' "$DEAD_SCHED_PID" > "$TK/dead.tick.lock/pid"
assert "tick lock: a dead recorded owner is refused and left untouched" \
    env CCT_ROUTING_STATE="$TSTATE" CCT_ROUTING_TICK_LOCK="$TK/dead.tick.lock" bash -c '
      source "$1"
      ! rs_tick_trylock
      [[ "$(cat "$RS_TICK_LOCK/pid")" == "$2" ]]' _ "$SLIB" "$DEAD_SCHED_PID"

# The short state-write lock is independently non-blocking for a tick.
mkdir -p "$TSTATE.lock"; echo $$ > "$TSTATE.lock/pid"
LOCK_START=$(date -u +%s)
OUT=$( ( set +e; cd "$REPO_DIR"; CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$TSTATE" bash "$CLI" tick --due --once 2>&1 ) )
LOCK_ELAPSED=$(( $(date -u +%s) - LOCK_START ))
rm -rf "$TSTATE.lock"
assert "tick: a live lock holder is REFUSED by name" \
    grep -q "another writer holds the routing-state lock" <<< "$OUT"
assert_eq "tick: the refusal is IMMEDIATE (a cron tick never queues)" "yes" \
    "$( [[ "$LOCK_ELAPSED" -le 5 ]] && echo yes || echo no )"
assert "lock: the scheduler acquires non-blockingly, B's supervisor lock still WAITS" \
    bash -c "grep -q 'rs_tick_trylock' '$SLIB' && grep -q 'rs_trylock' '$SLIB' && grep -q 'deliberately WAITS' '$SLIB'"
mkdir -p "$TK/dead-state.json.lock"
printf '%s\n' "$DEAD_SCHED_PID" > "$TK/dead-state.json.lock/pid"
assert "state lock: a scheduled writer never deletes a dead-owner lock" \
    env CCT_ROUTING_STATE="$TK/dead-state.json" bash -c '
      source "$1"
      ! rs_trylock
      [[ "$(cat "${RS_FILE}.lock/pid")" == "$2" ]]' _ "$SLIB" "$DEAD_SCHED_PID"

# CONCURRENCY, not a lock fixture: two real ticks, one due event. The
# claim (select + mark `probing` in ONE locked write) is what stops
# them sharing it — a tick that selected under the lock and probed
# after releasing it would produce two passes and mint `healthy` out
# of a single recovery.
CC="$TMP/concur"; mkdir -p "$CC"
printf '#!/usr/bin/env bash\nP=$(cat)\nE=$(printf "%%s\\n" "$P" | grep -oE "CCT_PROBE_OK:[0-9a-f]{20}" | tail -1)\necho LAUNCH >> "%s/launches"\nprintf CCT_TOOL_OK > "$CCT_PROBE_TOOL_FILE"\nprintf "{\\"result\\":\\"%%s\\"}\\n" "$E"\n' "$CC" > "$CC/pass.sh"
chmod +x "$CC/pass.sh"
CSTATE="$CC/state.json"
( set +e; CCT_ROUTING_STATE="$CSTATE" bash -c "source '$SLIB'; rs_schedule_probe c1 alpha $((NOW - 5)) due" ) >/dev/null 2>&1
CTICK() { ( set +e; cd "$REPO_DIR"
    CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$CSTATE" \
    CCT_ROUTING_PROBE_LEDGER="$CC/led-$1.json" CCT_ROUTING_PROBE_CMD="bash $CC/pass.sh" \
    bash "$CLI" tick --due --once 2>&1 ); }
CTICK a > "$CC/a.log" 2>&1 &
CTICK b > "$CC/b.log" 2>&1 &
wait
assert_eq "concurrency: two ticks, ONE due event, exactly ONE probe launched" "1" \
    "$(grep -c LAUNCH "$CC/launches" 2>/dev/null || true)"
assert_eq "concurrency: ...so the streak is 1, not 2" "1" \
    "$(jq -r '.profiles.alpha.consecutive_probe_successes' "$CSTATE")"
assert_eq "concurrency: ...and health was NOT minted from one recovery" "probe_due" \
    "$(jq -r '.profiles.alpha.state' "$CSTATE")"
assert "concurrency: the losing tick REFUSES by name (it never exits mute)" \
    bash -c "cat '$CC/a.log' '$CC/b.log' | grep -Eq 'another scheduler holds|another writer holds the routing-state lock'"
assert_eq "concurrency: generations come from the store's DURABLE sequence" "1" \
    "$(jq -r '.probe_seq' "$CSTATE")"
assert "concurrency: no process-derived generation survives in the tick" \
    bash -c "! grep -q '\\$\\$ \\* 1000' '$CLI'"

# The SEQUENTIAL case the lock cannot cover: tick B starts after tick A
# has already claimed and RELEASED the lock (A is still out probing).
# Only a CONSUMED schedule makes the due instant single-use.
CSEQ="$CC/seq.json"
( set +e; CCT_ROUTING_STATE="$CSEQ" bash -c "source '$SLIB'; rs_schedule_probe q1 alpha $((NOW - 5)) due" ) >/dev/null 2>&1
SEQ_CLAIM=$( set +e; CCT_ROUTING_STATE="$CSEQ" bash -c "source '$SLIB'; rs_claim_due $NOW" )
assert_eq "claim: the first scheduler claims the due profile" "alpha" "$(cut -f1 <<< "$SEQ_CLAIM")"
assert "claim: the lock is RELEASED once the claim is written (probing happens outside it)" \
    bash -c "[[ ! -d '$CSEQ.lock' ]]"
assert_eq "claim: a LATER scheduler finds nothing due — the schedule was consumed" "" \
    "$( set +e; CCT_ROUTING_STATE="$CSEQ" bash -c "source '$SLIB'; rs_claim_due $NOW" )"
assert_eq "claim: ...and the in-flight marker is what remains" "probing" \
    "$(jq -r '.profiles.alpha.state' "$CSEQ")"
assert_eq "claim: ...with no stale due instant left behind" "null" \
    "$(jq -r '.profiles.alpha.next_probe_at | tostring' "$CSEQ")"
assert_eq "claim: only the abandonment window may re-offer it" "alpha" \
    "$( set +e; CCT_ROUTING_STATE="$CSEQ" bash -c "source '$SLIB'; rs_claim_due \$(( $NOW + RS_PROBE_ABANDON_SEC + 10 ))" | cut -f1 )"
assert_eq "claim: nothing due is NO WRITE (an idle tick leaves the store byte-identical)" "same" \
    "$( cp "$CSEQ" "$CC/seq-before.json"
        ( set +e; CCT_ROUTING_STATE="$CSEQ" bash -c "source '$SLIB'; rs_claim_due $NOW" ) >/dev/null 2>&1
        cmp -s "$CSEQ" "$CC/seq-before.json" && echo same || echo differs )"

# the provider's OWN recovery timing must outrank a computed backoff
RA="$TMP/retry"; mkdir -p "$RA"
printf '#!/usr/bin/env bash\ncat > /dev/null\ncat "%s"\nexit 1\n' "$SCRIPT_DIR/fixtures/routing/api-429-text.out" > "$RA/429.sh"
chmod +x "$RA/429.sh"
RSTATE="$RA/state.json"
( set +e; CCT_ROUTING_STATE="$RSTATE" bash -c "source '$SLIB'; rs_schedule_probe r1 alpha $((NOW - 5)) due" ) >/dev/null 2>&1
RA_OUT=$( set +e; cd "$REPO_DIR"
    CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$RSTATE" \
    CCT_ROUTING_PROBE_LEDGER="$RA/led.json" CCT_ROUTING_PROBE_CMD="bash $RA/429.sh" \
    bash "$CLI" tick --due --once 2>/dev/null )
assert "evidence: rb_probe returns the provider's recovery timing as a third field" \
    bash -c "RES=\$( set +e; export CCT_ROUTING_PROBE_LEDGER='$RA/led2.json' CCT_ROUTING_PROBE_CMD='bash $RA/429.sh'
        source '$REPO_DIR/scripts/lib/routing-probe.sh'
        rb_probe '{\"id\":\"alpha\",\"backend\":\"claude-code\",\"model\":\"sonnet\",\"tool_profile\":\"chat-only\",\"credential_ref\":\"none\",\"endpoint_ref\":\"none\"}' 7 2>/dev/null )
        jq -e '.retry_after_sec == 30' <<< \"\$(cut -f3 <<< \"\$RES\")\""
assert "evidence: the tick SCHEDULES from Retry-After, not from backoff" \
    grep -q "next probe via retry_after" <<< "$RA_OUT"
# Retry-After: 30 lands ~30s out; the backoff for failure #1 is 60s
# +/- 20% jitter, so the two windows cannot overlap.
RA_DELTA=$(( $(jq -r '.profiles.alpha.next_probe_at' "$RSTATE") - $(date -u +%s) ))
assert_eq "evidence: ...at the instant the provider named, not a backoff window" "yes" \
    "$( [[ "$RA_DELTA" -ge 25 && "$RA_DELTA" -le 31 ]] && echo yes || echo "no ($RA_DELTA s)" )"
assert "evidence: no call site discards the probe's evidence with a literal {}" \
    bash -c "! grep -qE 'rd_next_probe_at .*fails \+ 1.* .\{\}.' '$CLI'"

# The THIRD precedence source has to be live on the real probe path.
# A's classifier reads headers and message text, not the subscription
# usage block, so rate_limits_resets_at would be permanently null and
# the source dead in production while T1's synthetic test passed.
RLCAP="$RA/rate-limits.json"
printf '{"type":"error","error":{"type":"rate_limit_error","message":"usage limit reached"},"rate_limits":{"five_hour":{"resets_at":"2099-07-01T00:00:00Z"},"weekly":{"resets_at":"2099-06-01T00:00:00Z"}}}\n' > "$RLCAP"
printf '#!/usr/bin/env bash\ncat > /dev/null\ncat "%s"\nexit 1\n' "$RLCAP" > "$RA/rl.sh"
chmod +x "$RA/rl.sh"
RLRES=$( set +e; export CCT_ROUTING_PROBE_LEDGER="$RA/led3.json" CCT_ROUTING_PROBE_CMD="bash $RA/rl.sh"
    source "$REPO_DIR/scripts/lib/routing-probe.sh"
    rb_probe '{"id":"alpha","backend":"claude-code","model":"sonnet","tool_profile":"chat-only","credential_ref":"none","endpoint_ref":"none"}' 9 2>/dev/null )
assert_eq "evidence: subscription rate_limits resets_at is recovered from the capture" \
    "2099-06-01T00:00:00Z" \
    "$(jq -r '.rate_limits_resets_at' <<< "$(cut -f3 <<< "$RLRES")" 2>/dev/null)"
assert "evidence: ...the EARLIEST window, not an arbitrary one" \
    bash -c "[[ \"\$(jq -r '.rate_limits_resets_at' <<< \"\$(cut -f3 <<< \"$RLRES\")\")\" != '2099-07-01T00:00:00Z' ]]"
assert "evidence: ...and it comes from the SAME capture the outcome was classified from" \
    bash -c "grep -q 'read from the probe capture' '$REPO_DIR/scripts/lib/routing-probe.sh'"
RLSTATE="$RA/rl-state.json"
( set +e; CCT_ROUTING_STATE="$RLSTATE" bash -c "source '$SLIB'; rs_schedule_probe rl1 alpha $((NOW - 5)) due" ) >/dev/null 2>&1
RLOUT=$( set +e; cd "$REPO_DIR"
    CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$RLSTATE" \
    CCT_ROUTING_PROBE_LEDGER="$RA/led4.json" CCT_ROUTING_PROBE_CMD="bash $RA/rl.sh" \
    bash "$CLI" tick --due --once 2>/dev/null )
assert "evidence: the tick schedules from rate_limits when it is the best evidence" \
    grep -q "next probe via rate_limits" <<< "$RLOUT"
# Compared as ABSOLUTE instants: sampling `now` twice and diffing both
# results makes the assertion fail whenever a second boundary falls
# between the two samples.
EARLIEST_EPOCH=$(date -u -j -f '%Y-%m-%dT%H:%M:%SZ' '2099-06-01T00:00:00Z' +%s 2>/dev/null \
                 || date -u -d '2099-06-01T00:00:00Z' +%s)
assert_eq "evidence: ...at the EARLIEST window, not the first one printed" "$EARLIEST_EPOCH" \
    "$(jq -r '.profiles.alpha.next_probe_at' "$RLSTATE")"
# reset_at from somewhere OTHER than the rate_limits block keeps its
# higher precedence — this only ever yields to a better parse of the
# same bytes, never to a different source.
RLH="$RA/hdr.json"
printf 'retry-after: 45\n{"type":"error","error":{"type":"rate_limit_error","message":"limit"},"rate_limits":{"weekly":{"resets_at":"2099-06-01T00:00:00Z"}}}\n' > "$RLH"
printf '#!/usr/bin/env bash\ncat > /dev/null\ncat "%s"\nexit 1\n' "$RLH" > "$RA/hdr.sh"
chmod +x "$RA/hdr.sh"
HRES=$( set +e; export CCT_ROUTING_PROBE_LEDGER="$RA/led5.json" CCT_ROUTING_PROBE_CMD="bash $RA/hdr.sh"
    source "$REPO_DIR/scripts/lib/routing-probe.sh"
    rb_probe '{"id":"alpha","backend":"claude-code","model":"sonnet","tool_profile":"chat-only","credential_ref":"none","endpoint_ref":"none"}' 11 2>/dev/null )
assert_eq "evidence: a Retry-After header still outranks the rate_limits window" "45" \
    "$(jq -r '.retry_after_sec | tostring' <<< "$(cut -f3 <<< "$HRES")" 2>/dev/null)"

echo ""
echo "== T3: wake — a closed replay, driven by REAL supervisor parks =="

# EVERY ledger below is written by the actual supervisor. A wake reads
# a run's disposition, its recorded identity and its run lock, and any
# of those hand-built by the test would only prove the test agrees
# with itself. In particular the (status, profile) pair matters: an
# UNATTENDED routing refusal terminates `failed`, not `parked`.
SUPV="$REPO_DIR/scripts/cooldown-supervisor.sh"
WK="$TMP/wake"; mkdir -p "$WK/dry"
# the repository contributes only a wake restriction; the structured
# invocation itself is recorded by the supervisor that parked the run
printf '{"schema_version":2,"profile":"advisory","routing":{"recovery":{"wake_enabled":true}}}' \
    > "$WK/default-wake.json"
printf '#!/usr/bin/env bash\ncat "$FIXTURE"\nexit 1\n' > "$WK/blocked.sh"
printf '#!/usr/bin/env bash\nsleep 8\nexit 0\n' > "$WK/slow.sh"
chmod +x "$WK/blocked.sh" "$WK/slow.sh"
WFIX="$SCRIPT_DIR/fixtures/routing/claude-weekly-limit.out"

# A live supervisor owns recovery for the run it is supervising. External
# cron remains useful for parked-run wake/failback, but a cooldown expiry
# must not become a permanent park merely because cron was never installed.
LIVE="$TMP/live-recovery"; mkdir -p "$LIVE/wt/specs/live-recovery"
printf -- '- [x] done\n' > "$LIVE/wt/specs/live-recovery/tasks.md"
( cd "$LIVE/wt" && git init -q && git config user.email t@t && git config user.name t \
  && git add -A && git commit -qm fixture )
LIVE_NOW=$(date -u +%s)
( set +e; CCT_ROUTING_STATE="$LIVE/state.json" bash -c \
  "source '$SLIB'; rs_set_profile live-cd alpha cooldown expired $((LIVE_NOW - 1)); rs_schedule_after_cooldown live-due alpha $((LIVE_NOW - 1)) due" ) >/dev/null 2>&1
LIVE_RC=0
( cd "$REPO_DIR"
  CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$LIVE/state.json" \
  CCT_ROUTING_PROBE_LEDGER="$LIVE/probes.json" CCT_ROUTING_PROBE_CMD="bash $TK/pass.sh" \
  CCT_SUPERVISOR_HARNESS_CMD='exit 0' \
  bash "$SUPV" live-recovery --routing --worktree "$LIVE/wt" --profile advisory \
    --max-attempts 2 --max-cooldowns 1 --cooldown-sec 0 --max-wall-sec 60 \
    > "$LIVE/supervisor.log" 2>&1 ) || LIVE_RC=$?
assert_eq "live recovery: cooldown expiry does not require an external scheduler" "0" "$LIVE_RC"
assert_eq "live recovery: the supervisor drove enough real canaries to qualify health" "healthy 2" \
    "$(jq -r '[.profiles.alpha.state, (.profiles.alpha.consecutive_probe_successes|tostring)] | join(" ")' "$LIVE/state.json")"
assert "live recovery: in-process tick ownership is journaled" \
    grep -q '"event":"routing_recovery_tick"' "$LIVE/wt/.cct/supervisor/live-recovery/events.jsonl"

# A second supervisor can auth-disable the selected profile after this
# attempt starts. The state guard must reject the stale success write, but
# that rejection is not permission to lose the already-persisted result or
# skip the durable checkpoint.
APPLY_RACE="$TMP/apply-race"; mkdir -p "$APPLY_RACE/wt/specs/apply-race"
printf -- '- [x] done\n' > "$APPLY_RACE/wt/specs/apply-race/tasks.md"
cat > "$APPLY_RACE/disable-during-attempt.sh" <<EOF
#!/usr/bin/env bash
source "$SLIB"
rs_set_profile concurrent-disable "\$CCT_ROUTING_PROFILE" disabled \
  "credentials revoked by concurrent supervisor" -
exit 0
EOF
( cd "$APPLY_RACE/wt" && git init -q && git config user.email t@t \
  && git config user.name t && git add -A && git commit -qm fixture )
APPLY_RACE_RC=0
( cd "$REPO_DIR"
  CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$APPLY_RACE/state.json" \
  CCT_SUPERVISOR_HARNESS_CMD="bash '$APPLY_RACE/disable-during-attempt.sh'" \
  bash "$SUPV" apply-race --routing --worktree "$APPLY_RACE/wt" --profile advisory \
    --max-attempts 2 --max-cooldowns 1 --cooldown-sec 0 --max-wall-sec 60 \
    > "$APPLY_RACE/supervisor.log" 2>&1 ) || APPLY_RACE_RC=$?
assert_eq "state race: a rejected stale success transition does not terminate the supervisor" "0" "$APPLY_RACE_RC"
assert_eq "state race: the concurrent auth disable remains authoritative" "disabled" \
    "$(jq -r '.profiles.alpha.state' "$APPLY_RACE/state.json")"
assert "state race: the rejected transition is journaled" \
    grep -q '"event":"routing_state_transition_rejected"' \
      "$APPLY_RACE/wt/.cct/supervisor/apply-race/events.jsonl"
assert "state race: the persisted result still reaches its durable checkpoint" \
    test -f "$APPLY_RACE/wt/.cct/auto-build/apply-race/routing/checkpoint-1.json"

# Whole-run, delegate, and reconcile launches all restart the tenure clock
# when they switch profiles; failback consumes this exact timestamp.
assert_eq "profile tenure: all three launch modes stamp routing_profile_since on a switch" "3" \
    "$(grep -c 'if .routing_profile != \\$p then .routing_profile_since = \\$n' "$SUPV")"

# park <name> <profile> [automation-json] -> a REAL parked routed run
park() {   # park <name> <profile> [automation-json|-] [extra supervisor args...]
    local n="$1" prof="$2" cfg="${3:--}"; shift 3 || shift $#
    local wt="$WK/$n"
    mkdir -p "$wt/specs/demo-$n"
    printf -- "- [x] done\n" > "$wt/specs/demo-$n/tasks.md"
    # A real repository fixture lets the wake validate this run's own
    # restriction document before it composes the effective policy.
    [[ "$cfg" == "-" ]] && cfg="$WK/default-wake.json"
    cp "$cfg" "$wt/specs/demo-$n/automation.json"
    ( cd "$wt" && git init -q 2>/dev/null
      git config user.email t@t && git config user.name t
      git add -A >/dev/null 2>&1
      git commit -qm "fixture" >/dev/null 2>&1 ) || true
    ( set +e; cd "$REPO_DIR"
      env FIXTURE="$WFIX" \
          CCT_SUPERVISOR_HARNESS_CMD="FIXTURE='$WFIX' bash '$WK/blocked.sh'" \
          CCT_ROUTING_PROBE_LEDGER="$WK/$n-probes.json" \
          CCT_ROUTING_PROBE_CMD="bash $TK/fail.sh" \
          CCT_SUPERVISOR_SLEEP=true \
          CCT_ROUTING_REGISTRY="$TK/reg.toml" \
          CCT_ROUTING_STATE="$WK/$n-state.json" \
          bash "$SUPV" "demo-$n" --routing --worktree "$wt" --profile "$prof" "$@" \
          > "$WK/$n-sup.log" 2>&1 )
    WRUN="$wt/.cct/supervisor/demo-$n/run.json"
    WLED="$wt/.cct/supervisor"
}
# WAKE <name> [state-file] -> the tick's wake output for that ledger
WAKE() {
    local n="$1" st="${2:-$WK/$1-state.json}"
    ( set +e; cd "$REPO_DIR"
      CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$st" \
      CCT_ROUTING_WAKE_DRYRUN="$WK/dry" \
      bash "$CLI" tick --due --once --wake --ledger-root "$WK/$n/.cct/supervisor" 2>&1 )
}
# a state file in which alpha has RECOVERED (wake is a consequence of
# recovery, so every positive case needs one)
recovered() { printf '{"schema_version":1,"profiles":{"alpha":{"state":"healthy","reason":"probe-verified","until":null,"healthy_since":%s,"consecutive_probe_successes":2}},"pools":{},"applied":{}}' "$NOW" > "$1"; }

park unatt unattended
assert_eq "wake: an unattended routing refusal really does terminate 'failed'" "failed" \
    "$(jq -r '.status' "$WRUN")"
assert "wake: ...for the routing_no_eligible_profile disposition" \
    bash -c "jq -r '.last_reason' '$WRUN' | grep -q '^routing_no_eligible_profile:'"
assert "recovery scheduling: a real pool cooldown schedules the failed profile's canary" \
    jq -e '.profiles.alpha.next_probe_at != null' "$WK/unatt-state.json"
assert "recovery scheduling: the real cooldown carries a due instant without a test-only scheduler call" \
    jq -e '.profiles.alpha.next_probe_at | type == "number"' "$WK/unatt-state.json"
assert_eq "wake: the supervisor records run IDENTITY, never a command vector" "null" \
    "$(jq -r '.routing_argv // "null"' "$WRUN")"
assert_eq "wake: the park minted generation 1 with nothing claimed" "1 null" \
    "$(jq -r '[(.routing_wake.generation|tostring), (.routing_wake.claimed|tostring)] | join(" ")' "$WRUN")"
assert "wake: the run lock is released when the supervisor exits" \
    bash -c "[[ ! -d '$WK/unatt/.cct/supervisor/demo-unatt/routing-run.lock' ]]"

# While every candidate is still cooling, a wake would re-park at once.
# The parked run's own state file is used as written by the supervisor,
# with the pool cooldown extended through B's primitive (the weekly
# fixture's reset instant is a fixed date that has since passed).
cp "$WK/unatt-state.json" "$WK/unatt-cooling.json"
( set +e; CCT_ROUTING_STATE="$WK/unatt-cooling.json" bash -c \
    "source '$SLIB'; rs_set_pool wk1 poolA cooldown 'quota exhausted' $((NOW + 3600))" ) >/dev/null 2>&1
assert_eq "wake: (fixture) the run's only candidate is genuinely still cooling" "pool:cooldown" \
    "$( set +e; CCT_ROUTING_STATE="$WK/unatt-cooling.json" bash -c "source '$SLIB'; rs_effective_state alpha poolA" )"
OUT=$(WAKE unatt "$WK/unatt-cooling.json")
assert "wake: a run whose candidates are ALL cooling is not woken (churn, not recovery)" \
    grep -q "no candidate is probe-qualified healthy" <<< "$OUT"
assert_eq "wake: ...and the generation stays unclaimed" "null" \
    "$(jq -r '.routing_wake.claimed | tostring' "$WRUN")"

# A candidate that is merely OUTSIDE cooldown is not recovered. Each
# of these is un-blocked and yet below the evidence bar the threshold
# exists to enforce — waking on any of them spends a supervisor on
# capacity that has not proven itself.
for st in probe_due probing unknown degraded; do
    printf '{"schema_version":1,"profiles":{"alpha":{"state":"%s","reason":"below threshold","until":null,"consecutive_probe_successes":1}},"pools":{},"applied":{}}' "$st" > "$WK/half-$st.json"
    jq '.routing_wake.claimed = null' "$WRUN" > "$WK/h.tmp" && mv "$WK/h.tmp" "$WRUN"
    OUTH=$(WAKE unatt "$WK/half-$st.json")
    assert "wake: '$st' is outside cooldown but NOT probe-qualified — no wake" \
        grep -q "no candidate is probe-qualified healthy" <<< "$OUTH"
done
# one pass below healthy_probes_required is the case the reviewer named
printf '{"schema_version":1,"profiles":{"alpha":{"state":"healthy","reason":"one pass","until":null,"healthy_since":%s,"consecutive_probe_successes":1}},"pools":{},"applied":{}}' "$NOW" > "$WK/one-pass.json"
jq '.routing_wake.claimed = null' "$WRUN" > "$WK/h.tmp" && mv "$WK/h.tmp" "$WRUN"
OUT=$(WAKE unatt "$WK/one-pass.json")
assert "wake: a SINGLE pass below healthy_probes_required cannot wake the run" \
    grep -q "no candidate is probe-qualified healthy" <<< "$OUT"
assert "wake: the refusal names the threshold it is enforcing" \
    grep -q "2 consecutive successes" <<< "$OUT"

# A profile can be probe-qualified while its POOL is still cooling:
# rs_probe_qualified reads profile evidence only, so the pool-level
# block has to be checked separately or a quota-exhausted pool would
# read as recovered.
recovered "$WK/pool-blocked.json"
( set +e; CCT_ROUTING_STATE="$WK/pool-blocked.json" bash -c \
    "source '$SLIB'; rs_set_pool pb1 poolA cooldown 'quota exhausted' $((NOW + 3600))" ) >/dev/null 2>&1
assert_eq "wake: (fixture) alpha is probe-qualified while poolA is cooling" "yes yes" \
    "$( set +e; CCT_ROUTING_STATE="$WK/pool-blocked.json" bash -c "source '$SLIB'
        rs_probe_qualified alpha 2 && printf yes || printf no
        printf ' '
        [[ \"\$(rs_effective_state alpha poolA)\" == pool:cooldown ]] && printf yes || printf no" )"
jq '.routing_wake.claimed = null' "$WRUN" > "$WK/h.tmp" && mv "$WK/h.tmp" "$WRUN"
OUTP=$(WAKE unatt "$WK/pool-blocked.json")
assert "wake: a cooling POOL blocks the wake even with a qualified profile" \
    grep -q "no candidate is probe-qualified healthy" <<< "$OUTP"
assert_eq "wake: ...and leaves the generation unclaimed" "null" \
    "$(jq -r '.routing_wake.claimed | tostring' "$WRUN")"

recovered "$WK/unatt-recovered.json"
jq '.routing_wake.claimed = null' "$WRUN" > "$WK/h.tmp" && mv "$WK/h.tmp" "$WRUN"
assert "wake: ledger publication uses a same-directory atomic rename" \
    bash -c "grep -Fq 'mktemp \"\$LEDGER_DIR/.run.json.XXXXXX\"' '$SUPV'"
# Default discovery follows this repository's registered worktrees. A git
# shim supplies the fixture worktree without mutating the developer's real
# worktree registry.
REAL_GIT=$(command -v git)
mkdir -p "$WK/git-bin"
cat > "$WK/git-bin/git" <<EOF
#!/usr/bin/env bash
if [[ "\$*" == *"worktree list --porcelain"* ]]; then
  printf 'worktree %s\\n' '$WK/unatt'
  exit 0
fi
exec '$REAL_GIT' "\$@"
EOF
chmod +x "$WK/git-bin/git"
OUT=$( set +e; cd "$REPO_DIR"
  PATH="$WK/git-bin:$PATH" CCT_ROUTING_REGISTRY="$TK/reg.toml" \
  CCT_ROUTING_STATE="$WK/unatt-recovered.json" CCT_ROUTING_WAKE_DRYRUN="$WK/dry" \
  bash "$CLI" tick --due --once --wake 2>&1 )
assert "wake discovery: the default finds normal --worktree ledgers" \
    grep -q "claimed wake generation 1" <<< "$OUT"
assert "wake: once a candidate is probe-verified healthy, the run IS woken" \
    grep -q "claimed wake generation 1" <<< "$OUT"
assert_eq "wake: the generation is CLAIMED durably" "1" \
    "$(jq -r '.routing_wake.claimed' "$WRUN")"
# the replay is RECONSTRUCTED: this installation's supervisor, a fixed
# flag list, and values re-validated out of the ledger
WARGV="$WK/dry/demo-unatt.argv"
assert_eq "wake: the executable is THIS installation's supervisor, never the ledger's" \
    "$SUPV" "$(head -1 "$WARGV")"
assert "wake: the reconstructed invocation carries the run's own identity" \
    bash -c "grep -qx -- '--routing' '$WARGV' && grep -qx 'demo-unatt' '$WARGV' && grep -qx -- '--profile' '$WARGV'"
assert "wake: ...and the closed reconstruction carries the code-owned default caps" \
    bash -c "grep -A1 -x -- '--max-attempts' '$WARGV' | tail -1 | grep -qx '20'"

OUT=$(WAKE unatt "$WK/unatt-recovered.json")
assert "wake: replaying a CLAIMED generation is a journaled no-op" \
    grep -q "generation 1 already claimed" <<< "$OUT"
assert_eq "wake: the no-op launched nothing" "0" "$(grep -c '1 run(s) woken' <<< "$OUT" || true)"

# An explicit operator-owned shared root is an intentional alternative to
# worktree-local ledgers and has its own binding check.
mkdir -p "$WK/shared/demo-unatt"
cp "$WK/unatt/.cct/supervisor/demo-unatt/run.json" "$WK/shared/demo-unatt/run.json"
jq '.routing_wake.claimed = null' "$WK/shared/demo-unatt/run.json" > "$WK/shared/tmp" \
  && mv "$WK/shared/tmp" "$WK/shared/demo-unatt/run.json"
SHARED_OUT=$( set +e; cd "$REPO_DIR"
  CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$WK/unatt-recovered.json" \
  CCT_ROUTING_WAKE_DRYRUN="$WK/shared-dry" \
  bash "$CLI" tick --due --once --wake --ledger-root "$WK/shared" 2>&1 )
assert "wake discovery: an explicit shared ledger root is accepted as its own binding" \
    grep -q "claimed wake generation 1" <<< "$SHARED_OUT"

# The real launch must carry the exact registry and ledger root that the
# tick validated. A --registry flag is not an exported variable, and a
# shared root cannot be derived from --worktree. Use a fake installation
# whose supervisor records the handoff and acknowledges that same ledger.
HANDOFF="$TMP/handoff-install"; mkdir -p "$HANDOFF"
cp "$CLI" "$HANDOFF/routing-cli.sh"
ln -s "$REPO_DIR/scripts/lib" "$HANDOFF/lib"
cp "$REPO_DIR/scripts/validate-automation-config.sh" "$HANDOFF/"
cat > "$HANDOFF/cooldown-supervisor.sh" <<'HEOF'
#!/usr/bin/env bash
set -eu
feat=""
for arg in "$@"; do feat="$arg"; done
printf '%s\n' "${CCT_ROUTING_REGISTRY-<unset>}" > "$HANDOFF_CAPTURE.registry"
printf '%s\n' "${CCT_SUPERVISOR_DIR-<unset>}" > "$HANDOFF_CAPTURE.ledger"
run="$CCT_SUPERVISOR_DIR/$feat/run.json"
tmp=$(mktemp "$CCT_SUPERVISOR_DIR/$feat/.ack.XXXXXX")
jq '.routing_wake.acked = .routing_wake.claimed' "$run" > "$tmp" && mv "$tmp" "$run"
HEOF
chmod +x "$HANDOFF/cooldown-supervisor.sh"
jq '.routing_wake.claimed = null | .routing_wake.acked = null' "$WK/shared/demo-unatt/run.json" \
  > "$WK/shared/tmp" && mv "$WK/shared/tmp" "$WK/shared/demo-unatt/run.json"
SHARED_PHYS=$(cd "$WK/shared" && pwd -P)
HANDOFF_OUT=$( set +e; cd "$REPO_DIR"
  env -u CCT_ROUTING_REGISTRY -u CCT_SUPERVISOR_DIR \
    CCT_ROUTING_STATE="$WK/unatt-recovered.json" HANDOFF_CAPTURE="$WK/handoff" \
    bash "$HANDOFF/routing-cli.sh" tick --due --once --wake \
      --registry "$TK/reg.toml" --ledger-root "$WK/shared" 2>&1 )
assert_eq "wake launch: child receives the registry validated via --registry" \
    "$TK/reg.toml" "$(cat "$WK/handoff.registry" 2>/dev/null)"
assert_eq "wake launch: child receives the admitted explicit ledger root" \
    "$SHARED_PHYS" "$(cat "$WK/handoff.ledger" 2>/dev/null)"
assert_eq "wake launch: the shared-ledger generation is acknowledged in place" "1" \
    "$(jq -r '.routing_wake.acked' "$WK/shared/demo-unatt/run.json")"

# a NEW park mints a new generation IN THE SAME WRITE as the disposition
park unatt unattended
assert_eq "wake: a fresh park mints generation 2 and clears the claim" "2 null" \
    "$(jq -r '[(.routing_wake.generation|tostring), (.routing_wake.claimed|tostring)] | join(" ")' "$WRUN")"
assert "wake: generation and disposition are ONE write (no two-step window)" \
    bash -c "grep -A6 'ledger_set .\.status = \\\$s | \.last_reason = \\\$r' '$SUPV' | grep -q 'routing_wake.generation ='"
OUT=$(WAKE unatt "$WK/unatt-recovered.json")
assert "wake: the new generation is wakeable again" grep -q "claimed wake generation 2" <<< "$OUT"

# ── an ATTENDED run parks; an operator owns it ──
park att advisory
assert_eq "wake: an ATTENDED routing refusal terminates 'parked', not 'failed'" "parked" \
    "$(jq -r '.status' "$WRUN")"
OUT=$(WAKE att "$WK/unatt-recovered.json")
assert "wake: an attended park is never auto-woken" \
    grep -q "an operator decides" <<< "$OUT"
assert_eq "wake: the attended refusal launched nothing" "0" \
    "$(grep -c '1 run(s) woken' <<< "$OUT" || true)"

# ── the ledger is UNTRUSTED: nothing in it may become executable ──
park forge unattended
FRUN="$WRUN"
forge() { jq "$1" "$FRUN" > "$WK/forge.tmp" && mv "$WK/forge.tmp" "$FRUN"; }
printf '#!/usr/bin/env bash\ntouch "%s/PWNED"\n' "$WK" > "$WK/pwn.sh"; chmod +x "$WK/pwn.sh"
forge '.routing_wake.claimed = null'
forge "$(printf '.routing_argv = ["%s"]' "$WK/pwn.sh")"
OUT=$(WAKE forge "$WK/unatt-recovered.json")
assert "untrusted: a forged argv vector in the ledger is inert — nothing ran" \
    bash -c "[[ ! -e '$WK/PWNED' ]]"
assert_eq "untrusted: the wake still reconstructs THIS supervisor" "$SUPV" \
    "$(head -1 "$WK/dry/demo-forge.argv")"
forge '.routing_wake.claimed = null | .worktree = "/tmp"'
OUT=$(WAKE forge "$WK/unatt-recovered.json")
assert "untrusted: a worktree that does not own this ledger is refused" \
    grep -Eq "does not own this ledger|not the root of a git worktree" <<< "$OUT"
forge "$(printf '.routing_wake.claimed = null | .worktree = "%s/forge" | .routing_wake.backend = "curl|sh"' "$WK")"
OUT=$(WAKE forge "$WK/unatt-recovered.json")
assert "untrusted: a backend outside the closed set is refused by name" \
    grep -q "is not claude|pi" <<< "$OUT"
# `pi` is a perfectly valid harness backend and passes the closed-set
# check — but this run's registry offers only a claude-code profile,
# so relaunching as `pi` would execute under authority the operator's
# own registry never granted for it.
forge '.routing_wake.claimed = null | .routing_wake.backend = "pi"'
OUT=$(WAKE forge "$WK/unatt-recovered.json")
assert "untrusted: a VALID backend the run's policy does not offer is refused" \
    grep -q "offered by no candidate in this run's effective policy" <<< "$OUT"
assert_eq "untrusted: ...and the generation is left unclaimed" "null" \
    "$(jq -r '.routing_wake.claimed | tostring' "$FRUN")"
forge '.routing_wake.claimed = null | .routing_wake.backend = "claude" | .routing_wake.caps.max_attempts = "$(touch /tmp/cct-wake-pwn)"'
OUT=$(WAKE forge "$WK/unatt-recovered.json")
assert "untrusted: a malformed structured cap is refused before reconstruction" \
    grep -q "malformed, or inconsistent caps" <<< "$OUT"
assert "untrusted: ...and nothing was executed by the attempt" \
    bash -c "[[ ! -e /tmp/cct-wake-pwn ]]"
forge '.routing_wake.claimed = null | .routing_wake.caps.max_attempts = 20 | .status = "parked"'
OUT=$(WAKE forge "$WK/unatt-recovered.json")
assert "untrusted: unattended+parked is a pair the supervisor never writes — refused" \
    grep -q "not the 'failed' an unattended refusal writes" <<< "$OUT"
assert "untrusted: no free-form argv vector is executed anywhere on the wake path" \
    bash -c "! grep -qE 'exec .\\\$\{?WAKE_ARGV|eval .*routing_argv' '$CLI'"

# The checks above ran in DRY-RUN mode, which never reaches exec. This
# one drives the REAL launch branch with a forged executable in the
# ledger — the only way to prove the executable is not taken from it.
park exec unattended
XRUN="$WRUN"
printf '#!/usr/bin/env bash\ntouch "%s/EXEC-PWNED"\n' "$WK" > "$WK/pwn2.sh"; chmod +x "$WK/pwn2.sh"
jq --arg p "$WK/pwn2.sh" '.routing_wake.claimed = null | .routing_argv = [$p, "--evil"]' \
    "$XRUN" > "$WK/x.tmp" && mv "$WK/x.tmp" "$XRUN"
XOUT=$( set +e; cd "$REPO_DIR"
    CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$WK/unatt-recovered.json" \
    bash "$CLI" tick --due --once --wake --ledger-root "$WK/exec/.cct/supervisor" 2>&1 )
assert "exec: the real (non-dry-run) wake launches" grep -q "relaunching the recorded run" <<< "$XOUT"
XWAIT=0
while [[ "$XWAIT" -lt 150 ]] && { [[ -d "$WK/exec/.cct/supervisor/demo-exec/routing-run.lock" ]] \
      || [[ "$(jq -r '.status' "$XRUN")" == "running" ]]; }; do sleep 0.1; XWAIT=$((XWAIT+1)); done
assert "exec: the forged executable in the ledger NEVER ran" \
    bash -c "[[ ! -e '$WK/EXEC-PWNED' ]]"
assert "exec: ...and the real supervisor did (it re-drove the run to a routing disposition)" \
    bash -c "jq -r '.last_reason' '$XRUN' | grep -q '^routing_'"

# ── the run lock: created by the SUPERVISOR, honoured by both sides ──
mkdir -p "$WK/live/specs/demo-live"
printf -- "- [x] done\n" > "$WK/live/specs/demo-live/tasks.md"
cp "$WK/default-wake.json" "$WK/live/specs/demo-live/automation.json"
( cd "$WK/live" && git init -q 2>/dev/null
  git config user.email t@t && git config user.name t
  git add -A >/dev/null 2>&1 && git commit -qm fixture >/dev/null 2>&1 ) || true
( set +e; cd "$REPO_DIR"
  env CCT_SUPERVISOR_HARNESS_CMD="bash '$WK/slow.sh'" CCT_SUPERVISOR_SLEEP=true \
      CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$WK/live-state.json" \
      bash "$SUPV" demo-live --routing --worktree "$WK/live" --profile unattended \
      >/dev/null 2>&1 ) &
LIVE_LOCK="$WK/live/.cct/supervisor/demo-live/routing-run.lock"
LIVE_WAIT=0
while [[ ! -d "$LIVE_LOCK" && "$LIVE_WAIT" -lt 100 ]]; do sleep 0.1; LIVE_WAIT=$((LIVE_WAIT+1)); done
LIVE_PID=$(cat "$LIVE_LOCK/pid" 2>/dev/null || echo "")
assert "runlock: a live routed supervisor holds an owner-aware run lock" \
    bash -c "[[ '$LIVE_PID' =~ ^[0-9]+$ ]] && kill -0 '$LIVE_PID' 2>/dev/null"
LRUN="$WK/live/.cct/supervisor/demo-live/run.json"
jq '.status="failed" | .last_reason="routing_no_eligible_profile: blocked" | .routing_wake.claimed=null' \
    "$LRUN" > "$WK/live.tmp" && mv "$WK/live.tmp" "$LRUN"
OUT=$(WAKE live "$WK/unatt-recovered.json")
assert "runlock: the tick refuses to wake a run a LIVE supervisor holds" \
    grep -q "holds the run lock" <<< "$OUT"
assert_eq "runlock: ...and does not claim the generation" "null" \
    "$(jq -r '.routing_wake.claimed | tostring' "$LRUN")"
SECOND=$( set +e; cd "$REPO_DIR"
    env CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$WK/live-state.json" \
        bash "$SUPV" demo-live --routing --worktree "$WK/live" --profile unattended 2>&1 )
assert "runlock: a second supervisor on the same ledger refuses too" \
    grep -q "already running feature" <<< "$SECOND"
wait
assert "runlock: the lock is released when that supervisor exits" \
    bash -c "[[ ! -d '$LIVE_LOCK' ]]"

# A dead recorded PID is not safe automatic-reclaim authority. The
# owner can release and a replacement acquire between a liveness check
# and deletion, so both wake and direct supervisor startup preserve the
# lock and require explicit operator recovery.
# Above the Linux/macOS PID range, so fixture subprocess churn cannot
# reuse it between this check and the wake invocation.
DEAD_RUN_PID=999999999
mkdir -p "$LIVE_LOCK"
printf '%s\n' "$DEAD_RUN_PID" > "$LIVE_LOCK/pid"
# The live supervisor completed after the earlier wake check and wrote
# its terminal state. Re-establish the exact wakeable disposition now,
# after that writer is gone, so this case reaches the dead-lock gate.
jq '.status="failed" | .last_reason="routing_no_eligible_profile: blocked" | .routing_wake.claimed=null' \
    "$LRUN" > "$WK/live.tmp" && mv "$WK/live.tmp" "$LRUN"
OUT=$(WAKE live "$WK/unatt-recovered.json")
assert "runlock: wake refuses a dead-owner lock instead of deleting it" \
    grep -q "dead owner pid $DEAD_RUN_PID" <<< "$OUT"
assert_eq "runlock: dead-owner wake refusal leaves the generation unclaimed" "null" \
    "$(jq -r '.routing_wake.claimed | tostring' "$LRUN")"
STALE_DIRECT=$( set +e; cd "$REPO_DIR"
    env CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$WK/live-state.json" \
        bash "$SUPV" demo-live --routing --worktree "$WK/live" --profile unattended 2>&1 )
assert "runlock: direct startup also preserves the dead-owner lock for manual recovery" \
    bash -c "grep -q 'Refusing racy automatic takeover' <<< \"\$1\" && [[ \$(cat '$LIVE_LOCK/pid') == '$DEAD_RUN_PID' ]]" _ "$STALE_DIRECT"
rm -rf "$LIVE_LOCK"

# ── the run lock covers ledger INITIALISATION, not just the run ──
# Two fresh supervisors racing from nothing: without the lock held
# before run.json is read or created, both initialise and one
# overwrites the other. Neither is started after the other's lock
# exists — they are launched together.
mkdir -p "$WK/race/specs/demo-race"
printf -- "- [x] done\n" > "$WK/race/specs/demo-race/tasks.md"
racer() { ( set +e; cd "$REPO_DIR"
    env CCT_SUPERVISOR_HARNESS_CMD="bash '$WK/slow.sh'" CCT_SUPERVISOR_SLEEP=true \
        CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$WK/race-state.json" \
        bash "$SUPV" demo-race --routing --worktree "$WK/race" --profile unattended \
        > "$WK/race-$1.log" 2>&1; echo "$?" > "$WK/race-$1.rc" ); }
racer a & racer b & wait
RACE_REFUSED=$(cat "$WK/race-a.log" "$WK/race-b.log" | grep -c "already running feature" || true)
assert_eq "init-race: exactly ONE of two simultaneous fresh supervisors is refused" "1" "$RACE_REFUSED"
assert_eq "init-race: ...and exactly one ledger exists, initialised once" "1" \
    "$(ls "$WK/race/.cct/supervisor/demo-race/run.json" 2>/dev/null | wc -l | tr -d ' ')"
assert "init-race: the refusal happens BEFORE the ledger is touched (lock precedes init)" \
    bash -c "grep -n 'RUN_LOCK=' '$SUPV' | head -1 | cut -d: -f1 | { read -r a; grep -n 'if \[\[ -f \"\\\$RUN\" \]\]' '$SUPV' | head -1 | cut -d: -f1 | { read -r b; [ \"\$a\" -lt \"\$b\" ]; }; }"

# ── the mode discriminator: bounded work is never auto-woken ──
# --delegate and --reconcile can both stop for
# routing_no_eligible_profile, and their identity is a task id plus
# packet/round state. Reconstructing them as an ordinary run would
# relaunch something ELSE, so they are refused BY NAME.
park mode unattended
MRUN="$WRUN"
assert_eq "mode: an ordinary routed run records mode 'run'" "run" \
    "$(jq -r '.routing_wake.mode' "$MRUN")"
assert_eq "mode: ...and its on-incomplete disposition" "park" \
    "$(jq -r '.routing_wake.on_incomplete' "$MRUN")"
for m in delegate reconcile; do
    jq --arg m "$m" '.routing_wake.claimed = null | .routing_wake.mode = $m' "$MRUN" > "$WK/m.tmp" && mv "$WK/m.tmp" "$MRUN"
    MOUT=$(WAKE mode "$WK/unatt-recovered.json")
    assert "mode: a --$m run is refused by name, never rebuilt as an ordinary run" \
        grep -q "this is a --$m run" <<< "$MOUT"
done
jq '.routing_wake.claimed = null | .routing_wake.mode = "sneaky"' "$MRUN" > "$WK/m.tmp" && mv "$WK/m.tmp" "$MRUN"
MOUT=$(WAKE mode "$WK/unatt-recovered.json")
assert "mode: the discriminator is CLOSED (an unknown mode is refused)" \
    grep -q "the mode discriminator is closed" <<< "$MOUT"
jq '.routing_wake.claimed = null | .routing_wake.mode = "run" | .routing_wake.on_incomplete = "whatever"' "$MRUN" > "$WK/m.tmp" && mv "$WK/m.tmp" "$MRUN"
MOUT=$(WAKE mode "$WK/unatt-recovered.json")
assert "mode: on-incomplete is validated against its closed enum too" \
    grep -q "is not park|relaunch" <<< "$MOUT"
jq '.routing_wake.claimed = null | .routing_wake.on_incomplete = "relaunch"' "$MRUN" > "$WK/m.tmp" && mv "$WK/m.tmp" "$MRUN"
MOUT=$(WAKE mode "$WK/unatt-recovered.json")
assert "mode: a non-default on-incomplete grant is refused for automatic wake" \
    grep -q "non-default operator grant.*resume it manually" <<< "$MOUT"

# ── wake outcomes are JOURNALED, not just printed ──
# A scheduled tick's stdout goes wherever cron sent it; the durable
# record has to be a closed named event with a timestamp.
park jrnl unattended
JRUN="$WRUN"; JLED="$WK/jrnl/.cct/supervisor/demo-jrnl"
jq '.routing_wake.claimed = null' "$JRUN" > "$WK/j.tmp" && mv "$WK/j.tmp" "$JRUN"
WAKE jrnl "$WK/unatt-recovered.json" >/dev/null 2>&1
assert "journal: a claim is persisted as a closed named event" \
    bash -c "jq -e 'select(.event == \"wake_claimed\") | .ts and .detail' '$JLED/events.jsonl' >/dev/null 2>&1"
WAKE jrnl "$WK/unatt-recovered.json" >/dev/null 2>&1
assert "journal: the claimed-generation no-op is persisted, not merely printed" \
    bash -c "jq -e 'select(.event == \"wake_replay_noop\")' '$JLED/events.jsonl' >/dev/null 2>&1"
jq '.routing_wake.claimed = null | .routing_wake.backend = "pi"' "$JRUN" > "$WK/j.tmp" && mv "$WK/j.tmp" "$JRUN"
WAKE jrnl "$WK/unatt-recovered.json" >/dev/null 2>&1
assert "journal: a refusal is persisted with its reason" \
    bash -c "jq -e 'select(.event == \"wake_refused\") | .detail | test(\"offered by no candidate\")' '$JLED/events.jsonl' >/dev/null 2>&1"
assert "journal: every persisted event name is in the closed vocabulary" \
    bash -c "! jq -e 'select(.event | startswith(\"wake_\")) | select([.event] | inside([\"wake_claimed\",\"wake_replay_noop\",\"wake_launch_failed\",\"wake_refused\",\"wake_acked\"]) | not)' '$JLED/events.jsonl' >/dev/null 2>&1"

# ── a claim is never consumed by a launch that did not happen ──
# A fake INSTALLATION whose supervisor dies instantly: the tick's own
# libs still resolve, but nothing ever acknowledges the launch.
FAKE="$TMP/fake-install"; mkdir -p "$FAKE"
cp "$CLI" "$FAKE/routing-cli.sh"
ln -sf "$REPO_DIR/scripts/lib" "$FAKE/lib"
cp "$REPO_DIR/scripts/validate-automation-config.sh" "$FAKE/"
# it dies before acknowledging; the CLI owns its reconstruction defaults
# instantly — a supervisor that launches and never acknowledges
printf '#!/usr/bin/env bash\nMAX_ATTEMPTS=20\nMAX_COOLDOWNS=12\nCOOLDOWN_SEC=300\nMAX_WALL_SEC=86400\nexit 3\n' > "$FAKE/cooldown-supervisor.sh"
chmod +x "$FAKE/cooldown-supervisor.sh"
park ack unattended
jq '.routing_wake.claimed = null' "$WRUN" > "$WK/a.tmp" && mv "$WK/a.tmp" "$WRUN"
AOUT=$( set +e; cd "$REPO_DIR"
    CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$WK/unatt-recovered.json" \
    RW_ACK_TICKS=10 bash "$FAKE/routing-cli.sh" tick --due --once --wake \
      --ledger-root "$WK/ack/.cct/supervisor" 2>&1 )
assert "launch-ack: an unacknowledged launch journals wake_launch_failed" \
    grep -q "wake_launch_failed" <<< "$AOUT"
assert_eq "launch-ack: ...and RELEASES the claim (the park stays retryable)" "null" \
    "$(jq -r '.routing_wake.claimed | tostring' "$WRUN")"
assert_eq "launch-ack: ...so it is not counted as woken" "0" \
    "$(grep -c '1 run(s) woken' <<< "$AOUT" || true)"
AOUT2=$( set +e; cd "$REPO_DIR"
    CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$WK/unatt-recovered.json" \
    RW_ACK_TICKS=10 bash "$FAKE/routing-cli.sh" tick --due --once --wake \
      --ledger-root "$WK/ack/.cct/supervisor" 2>&1 )
assert "launch-ack: a retry genuinely re-attempts the SAME generation" \
    grep -q "wake_launch_failed" <<< "$AOUT2"

# The acknowledgement is a DURABLE FACT, not a timing observation.
assert "launch-ack: the supervisor stamps 'acked' only after every startup prerequisite" \
    bash -c "grep -B2 'routing_wake.acked = .routing_wake.claimed' '$SUPV' | grep -q 'routing_wake.claimed != null'"
# a fast child that starts AND finishes between two polls still acks
park fast unattended
FRUN2="$WRUN"
jq '.routing_wake.claimed = null' "$FRUN2" > "$WK/f2.tmp" && mv "$WK/f2.tmp" "$FRUN2"
( set +e; cd "$REPO_DIR"        # a REAL launch — a dry run never execs
  CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$WK/unatt-recovered.json" \
  bash "$CLI" tick --due --once --wake \
    --ledger-root "$WK/fast/.cct/supervisor" >/dev/null 2>&1 )
assert_eq "launch-ack: (fixture) generation 1 was claimed" "1" \
    "$(jq -r '.routing_wake.claimed | tostring' "$FRUN2")"
FW=0
while [[ "$FW" -lt 150 ]] && [[ "$(jq -r '.routing_wake.acked | tostring' "$FRUN2")" == "null" ]]; do sleep 0.1; FW=$((FW+1)); done
assert_eq "launch-ack: a real relaunch leaves a DURABLE acked generation" "1" \
    "$(jq -r '.routing_wake.acked | tostring' "$FRUN2")"
assert_eq "launch-ack: ...and the claim is NOT cleared for an acknowledged launch" "1" \
    "$(jq -r '.routing_wake.claimed | tostring' "$FRUN2")"
# an old timeout must not clear a NEWER generation's claim
assert "launch-ack: the release is a generation CAS, not a blind write" \
    bash -c "grep -q 'if (.routing_wake.claimed == \\\$g) and (.routing_wake.acked != \\\$g)' '$CLI'"
park ackcas unattended
CRUN="$WRUN"
jq '.routing_wake.generation = 7 | .routing_wake.claimed = 7 | .routing_wake.acked = 7' "$CRUN" > "$WK/cc.tmp" && mv "$WK/cc.tmp" "$CRUN"
CASOUT=$( set +e; cd "$REPO_DIR"
    CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$WK/unatt-recovered.json" \
    RW_ACK_TICKS=5 bash "$FAKE/routing-cli.sh" tick --due --once --wake \
      --ledger-root "$WK/ackcas/.cct/supervisor" 2>&1 )
assert_eq "launch-ack: an ACKNOWLEDGED generation is never released by a later timeout" "7" \
    "$(jq -r '.routing_wake.claimed | tostring' "$CRUN")"
assert "launch-ack: a claim under a run lock we cannot attribute is left alone" \
    bash -c "grep -q 'refusing to clear a claim we cannot prove is stale' '$CLI'"

park claim-mismatch unattended
CMRUN="$WRUN"
jq '.routing_wake.generation = 8 | .routing_wake.claimed = 7' "$CMRUN" > "$WK/cm.tmp" && mv "$WK/cm.tmp" "$CMRUN"
CMOUT=$(WAKE claim-mismatch "$WK/unatt-recovered.json")
assert "launch-ack: an inconsistent older claim is refused, never overwritten" \
    grep -q "inconsistent claim for generation '7'" <<< "$CMOUT"
assert_eq "launch-ack: the inconsistent claim remains intact for inspection" "7" \
    "$(jq -r '.routing_wake.claimed' "$CMRUN")"

# A supervisor that REFUSES at startup must not consume the wake.
# Acknowledging at lock acquisition permanently burned a generation
# for a launch that never became runnable.
park refuse unattended
RFRUN="$WRUN"
jq '.routing_wake.claimed = 7 | .routing_wake.generation = 7 | .routing_wake.acked = null | .attempts = "corrupt"' \
    "$RFRUN" > "$WK/r.tmp" && mv "$WK/r.tmp" "$RFRUN"
RFOUT=$( set +e; cd "$REPO_DIR"
    env CCT_SUPERVISOR_HARNESS_CMD="bash '$WK/slow.sh'" CCT_SUPERVISOR_SLEEP=true \
        CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$WK/refuse-state.json" \
        bash "$SUPV" demo-refuse --routing --worktree "$WK/refuse" --profile unattended 2>&1
    echo "rc=$?" )
assert "startup-refusal: a corrupt ledger still fails closed" \
    grep -q "ledger is corrupt" <<< "$RFOUT"
assert_eq "startup-refusal: the wake is NOT acknowledged by a run that never became runnable" "null" \
    "$(jq -r '.routing_wake.acked | tostring' "$RFRUN")"
assert "startup-refusal: ...and no wake_acked event was journaled" \
    bash -c "! jq -e 'select(.event == \"wake_acked\")' '$WK/refuse/.cct/supervisor/demo-refuse/events.jsonl' >/dev/null 2>&1"
assert "startup-refusal: the ack is stamped only AFTER the fail-closed startup checks" \
    bash -c "A=\$(grep -n 'routing_wake.acked = .routing_wake.claimed' '$SUPV' | head -1 | cut -d: -f1)
             C=\$(grep -n 'fail_corrupt \"not valid JSON\"' '$SUPV' | head -1 | cut -d: -f1)
             T=\$(grep -n 'terminated_policy' '$SUPV' | sed -n '3p' | cut -d: -f1)
             [ \"\$A\" -gt \"\$C\" ] && [ \"\$A\" -gt \"\$T\" ]"

# ── structured invocation replay ──
# `--wake` is explicit operator action. The supervisor records the run
# arguments it actually received; the tick validates their closed shape
# and replays them with this installation's executable.
park caps unattended
CAPRUN="$WRUN"
jq '.routing_wake.claimed = null' "$CAPRUN" > "$WK/c.tmp" && mv "$WK/c.tmp" "$CAPRUN"
WAKE caps "$WK/unatt-recovered.json" >/dev/null 2>&1
assert "caps: the relaunch carries the code-owned default invocation" \
    bash -c "grep -A1 -x -- '--max-attempts' '$WK/dry/demo-caps.argv' | tail -1 | grep -qx '20'"

# A non-default operator cap has no independent authority source at the
# scheduled boundary. The mutable ledger can record it, but cannot grant it.
park narrow unattended - --max-attempts 3
NRUN="$WRUN"
assert_eq "caps: (fixture) the operator's original grant really was 3" "3" \
    "$(jq -r '.caps.max_attempts' "$NRUN")"
jq '.routing_wake.claimed = null' "$NRUN" > "$WK/n.tmp" && mv "$WK/n.tmp" "$NRUN"
NOUT=$(WAKE narrow "$WK/unatt-recovered.json")
assert "caps: a non-default cap is refused rather than treated as ledger-granted authority" \
    grep -q "original operator grant cannot be proven.*resume it manually" <<< "$NOUT"
assert_eq "caps: the refused non-default grant remains retryable" "null" \
    "$(jq -r '.routing_wake.claimed | tostring' "$NRUN")"

# Editing both persisted copies does not create authority. This was the
# hole hidden by a test that changed only one copy and let equality catch it.
jq '.caps.max_attempts = 999999999 | .routing_wake.caps = .caps | .routing_wake.claimed = null' \
    "$NRUN" > "$WK/n.tmp" && mv "$WK/n.tmp" "$NRUN"
NOUT=$(WAKE narrow "$WK/unatt-recovered.json")
assert "caps: forging both ledger copies still cannot widen automatic wake authority" \
    grep -q "original operator grant cannot be proven" <<< "$NOUT"

# The two persisted views must agree; partial corruption is a refusal,
# never a guessed invocation.
jq '.caps.max_attempts = 3 | .routing_wake.caps = .caps
    | .routing_wake.claimed = null | .routing_wake.caps.max_attempts = 4' \
    "$NRUN" > "$WK/n.tmp" && mv "$WK/n.tmp" "$NRUN"
NOUT=$(WAKE narrow "$WK/unatt-recovered.json")
assert "caps: inconsistent structured state is refused by name" \
    grep -q "malformed, or inconsistent caps" <<< "$NOUT"
assert_eq "caps: a refused inconsistent replay leaves the generation retryable" "null" \
    "$(jq -r '.routing_wake.claimed | tostring' "$NRUN")"

# The per-run restriction document is executable-validator guarded.
printf '{"schema_version":2,"profile":"advisory","routing":{"recovery":{"wake_enabled":"yes"}}}' \
    > "$WK/narrow/specs/demo-narrow/automation.json"
jq '.routing_wake.caps = .caps | .routing_wake.claimed = null' \
    "$NRUN" > "$WK/n.tmp" && mv "$WK/n.tmp" "$NRUN"
NOUT=$(WAKE narrow "$WK/unatt-recovered.json")
assert "policy: a malformed per-run automation.json refuses before composition" \
    grep -q "automation.json does not validate" <<< "$NOUT"
assert_eq "policy: malformed restrictions launch nothing" "null" \
    "$(jq -r '.routing_wake.claimed | tostring' "$NRUN")"

# ── FR-D5: active fallback runs are marked for next-boundary failback ──
# "Active" means a supervisor is ALIVE on the ledger, proven by the run
# lock — `status: running` survives a crash forever, and a marker on a
# dead ledger is one T4 would act on at a boundary that never comes.
# So this drives a REAL live routed supervisor.
FB="$TMP/failback"; mkdir -p "$FB/wt/specs/demo-fb"
printf -- "- [x] done\n" > "$FB/wt/specs/demo-fb/tasks.md"
cat > "$FB/reg.toml" <<'FEOF'
schema_version = 1
[policy]
enabled = true
preferred_profile = "alpha"
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
data_policy = "approved-cloud"
credential_mode = "claude-login"
FEOF
recovered "$FB/state.json"
( set +e; cd "$REPO_DIR"
  env CCT_SUPERVISOR_HARNESS_CMD="bash '$WK/slow.sh'" CCT_SUPERVISOR_SLEEP=true \
      CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$FB/sup-state.json" \
      bash "$SUPV" demo-fb --routing --worktree "$FB/wt" --profile unattended \
      >/dev/null 2>&1 ) &
FBLED="$FB/wt/.cct/supervisor/demo-fb"
FBW=0
while [[ ! -d "$FBLED/routing-run.lock" && "$FBW" -lt 100 ]]; do sleep 0.1; FBW=$((FBW+1)); done
FBRUN="$FBLED/run.json"
assert "failback: (fixture) a REAL supervisor is alive and holds the run lock" \
    bash -c "P=\$(cat '$FBLED/routing-run.lock/pid' 2>/dev/null); [[ \"\$P\" =~ ^[0-9]+\$ ]] && kill -0 \"\$P\" 2>/dev/null"
jq '.routing_profile = "beta" | .status = "running"' "$FBRUN" > "$FB/t.json" && mv "$FB/t.json" "$FBRUN"
FBTICK() { ( set +e; cd "$REPO_DIR"
    CCT_ROUTING_REGISTRY="$FB/reg.toml" CCT_ROUTING_STATE="${1:-$FB/state.json}" \
    bash "$CLI" tick --due --once --ledger-root "$FB/wt/.cct/supervisor" 2>&1 ); }
FBM="$FBLED/failback-marker.json"
FBOUT=$(FBTICK)
assert "failback: a LIVE run on a fallback profile is marked once the preferred one qualifies" \
    bash -c "[[ -r '$FBM' ]]"
assert_eq "failback: the marker names the preferred profile and the boundary rule" \
    "alpha failback_at_next_task_boundary" \
    "$(jq -r '[.preferred, .action] | join(" ")' "$FBM" 2>/dev/null)"
assert_eq "failback: ...and what it is currently running on" "beta" \
    "$(jq -r '.running_on' "$FBM" 2>/dev/null)"
assert "failback: the tick REPORTS the marking" grep -q "marked for failback" <<< "$FBOUT"
assert "failback: the marking is JOURNALED as a closed named event" \
    bash -c "jq -e 'select(.event == \"failback_marked\") | .ts and .detail' '$FBLED/events.jsonl' >/dev/null 2>&1"
assert "failback: the marker is a separate file — the live supervisor's ledger is untouched" \
    bash -c "! jq -e 'has(\"routing_failback\")' '$FBRUN' >/dev/null 2>&1"
cp "$FBM" "$FB/marker-before.json"
FBTICK >/dev/null 2>&1
assert "failback: re-marking the same qualification is idempotent (byte-identical)" \
    cmp -s "$FBM" "$FB/marker-before.json"
printf '{"schema_version":1,"profiles":{"alpha":{"state":"probe_due","reason":"one pass","until":null,"consecutive_probe_successes":1}},"pools":{},"applied":{}}' > "$FB/half.json"
rm -f "$FBM"
FBTICK "$FB/half.json" >/dev/null 2>&1
assert "failback: marking needs the SAME probe-qualified bar as wake, not merely un-blocked" \
    bash -c "[[ ! -e '$FBM' ]]"
jq '.routing_profile = "alpha"' "$FBRUN" > "$FB/t.json" && mv "$FB/t.json" "$FBRUN"
FBTICK >/dev/null 2>&1
assert "failback: a run ALREADY on the preferred profile is never marked" \
    bash -c "[[ ! -e '$FBM' ]]"
jq '.routing_profile = "beta"' "$FBRUN" > "$FB/t.json" && mv "$FB/t.json" "$FBRUN"
wait                     # the real supervisor exits; its run lock goes
assert "failback: (fixture) the supervisor has exited and released the lock" \
    bash -c "[[ ! -d '$FBLED/routing-run.lock' ]]"
jq '.status = "running"' "$FBRUN" > "$FB/t.json" && mv "$FB/t.json" "$FBRUN"
FBTICK >/dev/null 2>&1
assert "failback: a ledger still SAYING running with no live supervisor is NOT marked" \
    bash -c "[[ ! -e '$FBM' ]]"
# A CRASHED supervisor can leave its lock directory behind with a dead
# pid. D preserves that lock for explicit operator recovery; either way,
# it must never be mistaken for evidence that the run is active.
DEADPID=$( bash -c 'echo $$' )
while kill -0 "$DEADPID" 2>/dev/null; do DEADPID=$((DEADPID + 1)); done
mkdir -p "$FBLED/routing-run.lock"
echo "$DEADPID" > "$FBLED/routing-run.lock/pid"
FBTICK >/dev/null 2>&1
assert "failback: a STALE run lock (crashed supervisor, dead owner) is not liveness" \
    bash -c "[[ ! -e '$FBM' ]]"
printf 'not-a-pid\n' > "$FBLED/routing-run.lock/pid"
FBTICK >/dev/null 2>&1
assert "failback: an unverifiable lock owner is not liveness either (fail closed)" \
    bash -c "[[ ! -e '$FBM' ]]"
rm -rf "$FBLED/routing-run.lock"

echo "== T4: boundary-only failback with two-sided hysteresis =="
F4="$TMP/failback-boundary"; mkdir -p "$F4"
run_failback_case() { # <name> <mode> <successes> <healthy-since> <active-since> <marker:0|1> <repo-auto:true|false>
    local name="$1" mode="$2" successes="$3" hs="$4" as="$5" marker="$6" repo_auto="$7"
    local root="$F4/$name" wt="$F4/$name/wt" feat="fb-$name" led state nowf
    mkdir -p "$wt/specs/$feat"
    nowf=$(date -u +%s)
    cat > "$root-reg.toml" <<F4REG
schema_version = 1
[policy]
enabled = true
preferred_profile = "alpha"
failback = "$mode"
healthy_probes_required = 2
minimum_profile_dwell_sec = ${F4_DWELL:-100}
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
data_policy = "approved-cloud"
credential_mode = "claude-login"
[[profiles]]
id = "beta"
backend = "claude-code"
provider = "other-cloud"
model = "beta-model"
capability_tier = "tier1"
priority = 20
quota_pool = "poolB"
roles = ["build"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_mode = "claude-login"
F4REG
    if [[ "$repo_auto" == "false" ]]; then
        printf '{"schema_version":1,"routing":{"recovery":{"auto_failback_enabled":false}}}\n' > "$wt/specs/$feat/automation.json"
    elif [[ "$repo_auto" == "malformed" ]]; then
        printf '{"schema_version":1,"routing":{"recovery":{"auto_failback_enabled":"no"}}}\n' > "$wt/specs/$feat/automation.json"
    fi
    state="$root-state.json"
    jq -n --argjson now "$nowf" --argjson s "$successes" --argjson hs "$hs" '
      {schema_version:1,
       profiles:{alpha:{state:(if $s >= 2 then "healthy" else "probe_due" end),
                           reason:"fixture",until:null,
                           consecutive_probe_successes:$s,
                           healthy_since:(if $s >= 2 then $hs else null end),
                           next_probe_at:null}}, pools:{}, applied:{}}' > "$state"
    led="$wt/.cct/supervisor/$feat"; mkdir -p "$led"
    jq -n --arg f "$feat" --arg wt "$wt" --argjson now "$nowf" --argjson as "$as" '
      {schema_version:1,feature_id:$f,harness:"claude",worktree:$wt,
       profile:"advisory",status:"running",attempts:0,cooldowns:0,
       started_epoch:$now,routing_profile:"beta",routing_profile_since:$as,
       caps:{max_attempts:2,max_cooldowns:0,cooldown_sec:0,max_wall_sec:60}}' > "$led/run.json"
    if [[ "${F4_WITH_PROVISIONAL:-0}" == "1" ]]; then
        jq '.provisional = {task1:{verdict:"verified_provisional",evidence:"fixture"}}' \
            "$led/run.json" > "$root-run.tmp" && mv "$root-run.tmp" "$led/run.json"
    fi
    if [[ "$marker" == "1" ]]; then
        jq -n --argjson now "$nowf" '{schema:1,preferred:"alpha",running_on:"beta",
          threshold:2,qualified_since:$now,marked_at:$now,
          action:"failback_at_next_task_boundary"}' > "$led/failback-marker.json"
    fi
    ( set +e; cd "$REPO_DIR"
      CCT_ROUTING_REGISTRY="$root-reg.toml" CCT_ROUTING_STATE="$state" \
      CCT_ROUTING_RECONCILE_CMD="${F4_RECONCILE_CMD:-}" \
      CCT_SUPERVISOR_HARNESS_CMD="printf '%s\\n' \"\$CCT_ROUTING_PROFILE\" > '$root-selected'; exit 4" \
      bash "$SUPV" "$feat" --routing --worktree "$wt" --profile advisory \
           --max-attempts 2 --max-cooldowns 0 --cooldown-sec 0 --max-wall-sec 60 \
           >/dev/null 2>&1 ) || true
    cat "$root-selected" 2>/dev/null || echo "missing"
}
F4NOW=$(date -u +%s); F4OLD=$((F4NOW - 1000))
assert_eq "failback boundary: no tick marker means the active fallback stays pinned" "beta" \
    "$(run_failback_case no-marker auto 2 "$F4OLD" "$F4OLD" 0 true)"
assert_eq "failback hysteresis: a below-threshold preferred profile cannot switch" "beta" \
    "$(run_failback_case threshold auto 1 "$F4OLD" "$F4OLD" 1 true)"
assert_eq "failback hysteresis: preferred-profile dwell independently blocks" "beta" \
    "$(run_failback_case preferred-dwell auto 2 "$F4NOW" "$F4OLD" 1 true)"
assert_eq "failback hysteresis: active-profile dwell independently blocks" "beta" \
    "$(run_failback_case active-dwell auto 2 "$F4OLD" "$F4NOW" 1 true)"
assert_eq "failback boundary: both dwell checks plus threshold select the preferred profile" "alpha" \
    "$(run_failback_case switches auto 2 "$F4OLD" "$F4OLD" 1 true)"
F4_DWELL=0
assert_eq "failback hysteresis: zero dwell does not invent a one-boundary delay for a legacy ledger" "alpha" \
    "$(run_failback_case zero-dwell auto 2 "$F4OLD" null 1 true)"
unset F4_DWELL
assert "failback boundary: the switch is journaled by name" \
    bash -c "grep -q '\"event\":\"routing_failback\"' '$F4/switches/wt/.cct/supervisor/fb-switches/events.jsonl'"
assert_eq "failback policy: failback=operator pins the active profile" "beta" \
    "$(run_failback_case operator operator 2 "$F4OLD" "$F4OLD" 1 true)"
assert_eq "failback policy: the repository restriction pins the active profile" "beta" \
    "$(run_failback_case repo-veto auto 2 "$F4OLD" "$F4OLD" 1 false)"
assert_eq "failback policy: malformed repository restrictions execute nothing" "missing" \
    "$(run_failback_case malformed-policy auto 2 "$F4OLD" "$F4OLD" 1 malformed)"
assert_eq "failback policy: malformed restrictions leave the parent ledger untouched" "running" \
    "$(jq -r '.status' "$F4/malformed-policy/wt/.cct/supervisor/fb-malformed-policy/run.json")"
F4_WITH_PROVISIONAL=1
F4_RECONCILE_CMD='printf "%s\n" "$CCT_ROUTING_ARTIFACT_DIR" > "$(dirname "$CCT_RECOVERY_RECONCILE_RUN")/artifact-dir.txt"; T=$(mktemp "$(dirname "$CCT_RECOVERY_RECONCILE_RUN")/.reconcile.XXXXXX") || exit 1; jq --arg t "$CCT_RECOVERY_RECONCILE_TASK" ".provisional[\$t].verdict = \"accepted\"" "$CCT_RECOVERY_RECONCILE_RUN" > "$T" && mv "$T" "$CCT_RECOVERY_RECONCILE_RUN"'
assert_eq "reconcile-on-recovery: a pending provisional record is handled before failback" "alpha" \
    "$(run_failback_case reconcile auto 2 "$F4OLD" "$F4OLD" 1 true)"
assert_eq "reconcile-on-recovery: the terminal C verdict is imported into the parent ledger" "accepted" \
    "$(jq -r '.provisional.task1.verdict' "$F4/reconcile/wt/.cct/supervisor/fb-reconcile/run.json")"
assert "reconcile-on-recovery: the import is journaled before the failback" \
    bash -c "E='$F4/reconcile/wt/.cct/supervisor/fb-reconcile/events.jsonl'; test \"\$(grep -n routing_reconcile_on_recovery \"\$E\" | head -1 | cut -d: -f1)\" -lt \"\$(grep -n routing_failback \"\$E\" | tail -1 | cut -d: -f1)\""
assert "reconcile-on-recovery: the child writes routing artifacts inside its private recovery bundle" \
    bash -c "P=\$(cat '$F4/reconcile/wt/.cct/supervisor/fb-reconcile/recovery-reconcile/'*/ledger/fb-reconcile/artifact-dir.txt 2>/dev/null); [[ \"\$P\" == *'/recovery-reconcile/'*'/routing' ]]"
F4_RECONCILE_CMD='exit 4'
assert_eq "reconcile-on-recovery: a failed child parks before any preferred-profile work runs" "missing" \
    "$(run_failback_case reconcile-fails auto 2 "$F4OLD" "$F4OLD" 1 true)"
assert_eq "reconcile-on-recovery: a failed child parks the parent with a closed reason" "parked" \
    "$(jq -r '.status' "$F4/reconcile-fails/wt/.cct/supervisor/fb-reconcile-fails/run.json")"
assert "reconcile-on-recovery: a failed child leaves the failback marker retryable" \
    test -f "$F4/reconcile-fails/wt/.cct/supervisor/fb-reconcile-fails/failback-marker.json"
assert "reconcile-on-recovery: the failed child evidence is journaled before parking" \
    grep -q 'reconciliation parked before failback' "$F4/reconcile-fails/wt/.cct/supervisor/fb-reconcile-fails/events.jsonl"
unset F4_WITH_PROVISIONAL F4_RECONCILE_CMD

# ── the repository restriction, resolved PER RUN ──
printf '{"schema_version":1,"routing":{"recovery":{"wake_enabled":false}}}' > "$WK/norecover.json"
assert "policy: routing.recovery.wake_enabled is PROMOTED (the validator accepts it)" \
    bash -c "bash '$REPO_DIR/scripts/validate-automation-config.sh' '$WK/norecover.json' >/dev/null 2>&1"
printf '{"schema_version":1,"routing":{"recovery":{"probe_interval_sec":60}}}' > "$WK/badrec.json"
assert "policy: the recovery block is CLOSED (an unknown key is refused by name)" \
    bash -c "bash '$REPO_DIR/scripts/validate-automation-config.sh' '$WK/badrec.json' 2>&1 | grep -q \"unknown key 'routing.recovery.probe_interval_sec'\""
assert_eq "policy: an explicit false survives composition (no jq // widening)" "false" \
    "$(CCT_ROUTING_REGISTRY="$TK/reg.toml" bash -c "source '$REPO_DIR/scripts/lib/routing-config.sh'; rc_wake_allowed \"\$(rc_effective '$TK/reg.toml' '$WK/norecover.json')\"")"
assert_eq "policy: an absent block restricts nothing" "true" \
    "$(CCT_ROUTING_REGISTRY="$TK/reg.toml" bash -c "source '$REPO_DIR/scripts/lib/routing-config.sh'; rc_wake_allowed \"\$(rc_effective '$TK/reg.toml' -)\"")"
printf '{"schema_version":1,"routing":{"recovery":{"auto_failback_enabled":false}}}' > "$WK/nofailback.json"
assert_eq "policy: an explicit automatic-failback veto survives composition" "false" \
    "$(CCT_ROUTING_REGISTRY="$TK/reg.toml" bash -c "source '$REPO_DIR/scripts/lib/routing-config.sh'; rc_auto_failback_allowed \"\$(rc_effective '$TK/reg.toml' '$WK/nofailback.json')\"")"
park norec unattended "$WK/norecover.json"
OUT=$(WAKE norec "$WK/unatt-recovered.json")
assert "policy: a repository that forbids wake is refused BY NAME" \
    grep -q "wake_enabled = false" <<< "$OUT"
assert_eq "policy: ...and its generation is left unclaimed" "null" \
    "$(jq -r '.routing_wake.claimed | tostring' "$WRUN")"
assert "policy: each run's restriction document is validated before composition" \
    bash -c "grep -A8 'candidate_cfg=\"\$wt/specs/\$feat/automation.json\"' '$CLI' | grep -q 'validate-automation-config.sh'"

echo "== T5: explicit operator re-enable =="
ENSTATE="$TMP/enable-state.json"
( set +e; CCT_ROUTING_STATE="$ENSTATE" bash -c "source '$SLIB'; rs_set_profile auth1 alpha disabled 'credential rejected' -" ) >/dev/null 2>&1
ENOUT=$(cd "$REPO_DIR"; CCT_ROUTING_REGISTRY="$TK/reg.toml" CCT_ROUTING_STATE="$ENSTATE" \
    bash "$REPO_DIR/scripts/cct" routing enable alpha 2>&1)
assert_eq "enable: auth-disabled moves only to probe_due" "probe_due" \
    "$(jq -r '.profiles.alpha.state' "$ENSTATE")"
assert "enable: the next probe is due immediately" \
    bash -c "N=\$(date -u +%s); A=\$(jq -r '.profiles.alpha.next_probe_at' '$ENSTATE'); [[ \$A -le \$N ]]"
assert_eq "enable: old health evidence is cleared" "0 null" \
    "$(jq -r '[.profiles.alpha.consecutive_probe_successes, (.profiles.alpha.healthy_since|tostring)] | join(" ")' "$ENSTATE")"
assert "enable: the operator action is durable and named" \
    jq -e '.operator_events[-1] | .event == "routing_operator_enable" and .profile == "alpha"' "$ENSTATE"
assert "enable: output says a canary is still required" grep -q "must pass its canary" <<< "$ENOUT"
assert "enable: a second invocation refuses because the profile is no longer disabled" \
    bash -c "cd '$REPO_DIR'; ! CCT_ROUTING_REGISTRY='$TK/reg.toml' CCT_ROUTING_STATE='$ENSTATE' bash '$REPO_DIR/scripts/cct' routing enable alpha >/dev/null 2>&1"
assert "enable: an unknown profile is refused by name" \
    bash -c "cd '$REPO_DIR'; CCT_ROUTING_REGISTRY='$TK/reg.toml' CCT_ROUTING_STATE='$ENSTATE' bash '$CLI' enable ghost 2>&1 | grep -q 'not declared'"
( set +e; CCT_ROUTING_STATE="$ENSTATE" bash -c "source '$SLIB'; rs_set_profile auth2 alpha disabled 'credential rejected again' -" ) >/dev/null 2>&1
assert "enable: automatic scheduling cannot exit auth-disabled" \
    bash -c "! CCT_ROUTING_STATE='$ENSTATE' bash -c \"source '$SLIB'; rs_schedule_probe auto1 alpha \$(date -u +%s) automatic\" >/dev/null 2>&1"
assert_eq "enable: the refused automatic path leaves disabled intact" "disabled" \
    "$(jq -r '.profiles.alpha.state' "$ENSTATE")"
assert "enable: the generic setter cannot move auth-disabled to unknown" \
    bash -c "! CCT_ROUTING_STATE='$ENSTATE' bash -c \"source '$SLIB'; rs_set_profile auto2 alpha unknown automatic -\" >/dev/null 2>&1"
assert "enable: the generic setter cannot move auth-disabled to cooldown" \
    bash -c "! CCT_ROUTING_STATE='$ENSTATE' bash -c \"source '$SLIB'; rs_set_profile auto3 alpha cooldown automatic \$((\$(date -u +%s) + 60))\" >/dev/null 2>&1"
assert_eq "enable: auth-disable clears every stale due schedule" "null" \
    "$(jq -r '.profiles.alpha.next_probe_at | tostring' "$ENSTATE")"
assert_eq "enable: a scheduler cannot claim an auth-disabled profile" "" \
    "$(CCT_ROUTING_STATE="$ENSTATE" bash -c "source '$SLIB'; rs_claim_due \$(date -u +%s)" 2>/dev/null)"
assert "enable: late success evidence cannot race auth-disabled back to healthy" \
    bash -c "! CCT_ROUTING_STATE='$ENSTATE' bash -c \"source '$SLIB'; rs_mark_success late-success alpha\" >/dev/null 2>&1 && [[ \$(jq -r '.profiles.alpha.state' '$ENSTATE') == disabled ]]"

echo ""
echo "========================================="
echo "  routing-recovery tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_RECOVERY_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_RECOVERY_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
