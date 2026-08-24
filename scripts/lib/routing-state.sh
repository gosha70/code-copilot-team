#!/usr/bin/env bash
# routing-state.sh — the circuit/quota-pool state store (#251 T1,
# increment B of #109; plan decision 4 + the frozen crash-ordering
# contract of decision 5).
#
# Owns ~/.code-copilot-team/routing-state.json (override:
# CCT_ROUTING_STATE — the same variable increment A's read-only
# `cct routing status` honors). Properties this file guarantees:
#
#   ATOMIC   every write is temp+rename in the state file's own
#            directory; a reader can never observe a torn document.
#   LOCKED   read-modify-write happens under an exclusive mkdir lock
#            (<state>.lock) carrying its OWNER PID. Stale takeover
#            requires threshold age AND a confirmed-dead owner; a
#            hung-but-LIVE owner keeps the lock (safety over
#            liveness — two writers would lose updates even though
#            rename prevents torn JSON), and malformed/unverifiable
#            owner metadata FAILS CLOSED. Unlock is owner-aware: a
#            process can only remove its own lock.
#   IDEMPOTENT  mutations are keyed by attempt id (decision 5 step 4):
#            an id already recorded in `.applied` is a journaled
#            no-op, so replaying checkpoint processing can never
#            apply the same failure action twice. The applied set is
#            NOT pruned in increment B — the idempotency horizon is
#            part of the crash contract, not a cache; compaction may
#            arrive only with a durable high-watermark proving an
#            evicted id can never re-enter recovery.
#   FAIL-CLOSED  an unreadable/corrupt/partial state file is REFUSED
#            (exit 2 with guidance), never treated as empty — acting
#            on guessed circuit state could widen authority.
#   DECAY    re-eligibility is TIME-BASED and read-side: an entry
#            whose `until` has passed reads as `unknown` — never
#            `healthy` (B has no probes; increment D hooks here).
#            `disabled` (auth) entries carry no `until` and never
#            decay; operator action or D's probes re-enable them.
#   POOL>PROFILE  a blocked pool outranks its member profiles at
#            selection time.
#
# bash 3.2; jq only (no new dependency).

RS_FILE="${CCT_ROUTING_STATE:-$HOME/.code-copilot-team/routing-state.json}"
RS_LOCK_STALE_SEC="${CCT_ROUTING_LOCK_STALE_SEC:-60}"

RS_SKELETON='{"schema_version":1,"profiles":{},"pools":{},"applied":{}}'

rs_now() { date -u +%s; }

# rs_journal is overridable by the embedding supervisor; standalone it
# writes to stderr so nothing is silent.
if ! declare -F rs_journal >/dev/null 2>&1; then
    rs_journal() { echo "routing-state: $1: $2" >&2; }
fi

# ── lock (owner-aware) ───────────────────────────────────────────────
rs_lock() {
    local dir="${RS_FILE}.lock" waited=0
    while ! mkdir "$dir" 2>/dev/null; do
        local age now mtime owner
        now=$(rs_now)
        mtime=$(stat -f %m "$dir" 2>/dev/null || stat -c %Y "$dir" 2>/dev/null || echo "$now")
        age=$((now - mtime))
        if [[ "$age" -ge "$RS_LOCK_STALE_SEC" ]]; then
            owner=$(cat "$dir/pid" 2>/dev/null || echo "")
            if [[ ! "$owner" =~ ^[0-9]+$ ]]; then
                # Threshold passed but the owner cannot be verified —
                # FAIL CLOSED rather than steal an unattributable lock.
                echo "routing-state: lock $dir is past the stale threshold but its owner is unverifiable (missing/malformed pid) — refusing takeover; inspect and remove the lock manually if it is truly dead" >&2
                return 2
            fi
            if kill -0 "$owner" 2>/dev/null; then
                # Hung-but-LIVE owner keeps the lock: two writers would
                # lose updates even though rename prevents torn JSON.
                rs_journal "lock_busy_live_owner" "lock $dir is ${age}s old but owner pid $owner is ALIVE — waiting, never stealing"
            else
                rs_journal "lock_takeover" "stale lock (${age}s >= ${RS_LOCK_STALE_SEC}s) at $dir with CONFIRMED-DEAD owner pid $owner taken over"
                rm -rf "$dir" 2>/dev/null || true
                continue
            fi
        fi
        sleep 1
        waited=$((waited + 1))
        if [[ "$waited" -gt $((RS_LOCK_STALE_SEC * 2)) ]]; then
            echo "routing-state: could not acquire $dir (busy)" >&2
            return 2
        fi
    done
    echo "$$" > "${dir}/pid"
}
rs_unlock() {
    local dir="${RS_FILE}.lock"
    # Owner-aware: only the recording process may remove the lock, so
    # one process can never remove a replacement lock.
    if [[ "$(cat "$dir/pid" 2>/dev/null)" == "$$" ]]; then
        rm -rf "$dir" 2>/dev/null || true
    fi
}

# ── read (fail-closed) ───────────────────────────────────────────────
# rs_read -> the current document on stdout.
# Absent file => the empty skeleton (a NEVER-WRITTEN store is genuinely
# empty). Present-but-unreadable/corrupt/wrong-shape => exit 2 with
# guidance — never silently treated as empty.
rs_read() {
    if [[ ! -e "$RS_FILE" ]]; then
        printf '%s' "$RS_SKELETON"
        return 0
    fi
    local doc
    if ! doc=$(jq -ce '.' "$RS_FILE" 2>/dev/null); then
        echo "routing-state: $RS_FILE exists but is not readable JSON — refusing to act on corrupt circuit state (inspect or remove the file, then re-run)" >&2
        return 2
    fi
    if ! jq -e 'type == "object" and .schema_version == 1
                and (.profiles | type == "object")
                and (.pools | type == "object")
                and (.applied | type == "object")' >/dev/null 2>&1 <<< "$doc"; then
        echo "routing-state: $RS_FILE does not match the schema_version-1 shape — refusing to act on partial or foreign state" >&2
        return 2
    fi
    printf '%s' "$doc"
}

# ── write (atomic) ───────────────────────────────────────────────────
_rs_write() {  # <json-doc>
    local dir tmp
    dir=$(dirname "$RS_FILE")
    mkdir -p "$dir"
    tmp=$(mktemp "$dir/.routing-state.XXXXXX") || return 1
    printf '%s\n' "$1" > "$tmp"
    mv -f "$tmp" "$RS_FILE"
}

# ── idempotent apply (decision 5 step 4) ─────────────────────────────
# rs_apply <attempt_id> <jq-program> [jq args...]
# Under the lock: read (fail-closed), no-op when attempt_id was
# already applied (journaled), else run the jq program over the
# document, stamp .applied, prune, write atomically.
rs_apply() {
    local attempt_id="$1" prog="$2"; shift 2
    rs_lock || return 2
    local doc rc=0
    doc=$(rs_read) || { rc=$?; rs_unlock; return $rc; }
    if jq -e --arg id "$attempt_id" '.applied | has($id)' >/dev/null 2>&1 <<< "$doc"; then
        rs_journal "apply_noop" "attempt '$attempt_id' already applied — idempotent no-op"
        rs_unlock
        return 0
    fi
    local newdoc
    if ! newdoc=$(jq -ce --arg __attempt "$attempt_id" --argjson __now "$(rs_now)" \
        "$prog
         | .applied[\$__attempt] = \$__now" \
        "$@" <<< "$doc" 2>/dev/null); then
        echo "routing-state: mutation for attempt '$attempt_id' failed to evaluate — nothing written" >&2
        rs_unlock
        return 1
    fi
    _rs_write "$newdoc" || { rs_unlock; return 1; }
    rs_unlock
}

# ── the closed state vocabulary (#257 D T1; plan decision 1) ─────────
# Circuit states, probe-EXECUTION markers, and probe EVIDENCE are
# kept explicitly distinct (owner pin):
#   circuit:   unknown | cooldown | disabled | healthy | degraded
#   execution: probe_due | probing   (in-flight/scheduling markers —
#              NEVER health claims, never degradation)
#   evidence:  consecutive_probe_successes / healthy_since /
#              last_probe_at (separate fields, never inferred from
#              the state word)
# `degraded` is round-tripped but no D path emits it (recorded
# deviation). The generic setters below accept ONLY the states B
# writes (cooldown/disabled/unknown) — `healthy` is enterable
# exclusively through REAL EVIDENCE (rs_probe_pass at threshold, or
# B's frozen rs_mark_success on a genuinely successful attempt), and
# the probe markers only through the rs_probe_* primitives, so no
# call site can mint health or fake an in-flight probe.
RS_STATES="unknown cooldown disabled healthy degraded probe_due probing"
RS_SETTER_STATES="unknown cooldown disabled"

rs_state_valid() { [[ " $RS_STATES " == *" $1 "* ]]; }

# Convenience mutations (all through rs_apply's idempotency):
# rs_set_profile <attempt_id> <profile> <state> <reason> <until-epoch|->
rs_set_profile() {
    local id="$1" p="$2" st="$3" why="$4" until="${5:--}"
    if [[ " $RS_SETTER_STATES " != *" $st "* ]]; then
        echo "routing-state: rs_set_profile refuses state '$st' — healthy requires real evidence (rs_probe_pass/rs_mark_success) and probe markers require the rs_probe_* primitives" >&2
        return 1
    fi
    rs_apply "$id" \
        '.profiles[$p] = ((.profiles[$p] // {}) + {state:$st, reason:$why,
                          until:(if $until == "-" then null else ($until|tonumber) end),
                          failed_at:$__now})' \
        --arg p "$p" --arg st "$st" --arg why "$why" --arg until "$until"
}
# rs_set_pool <attempt_id> <pool> <state> <reason> <until-epoch|->
rs_set_pool() {
    local id="$1" pool="$2" st="$3" why="$4" until="${5:--}"
    if [[ " $RS_SETTER_STATES " != *" $st "* ]]; then
        echo "routing-state: rs_set_pool refuses state '$st' — healthy requires real evidence and probe markers require the rs_probe_* primitives" >&2
        return 1
    fi
    rs_apply "$id" \
        '.pools[$pool] = ((.pools[$pool] // {}) + {state:$st, reason:$why,
                          until:(if $until == "-" then null else ($until|tonumber) end),
                          failed_at:$__now})' \
        --arg pool "$pool" --arg st "$st" --arg why "$why" --arg until "$until"
}
# rs_mark_success <attempt_id> <profile>
# B's frozen behavior, deliberately UNCHANGED by D: a successful
# supervised attempt is EXECUTION evidence. It records B's `healthy`
# word (byte-compatible with pre-D behavior) but stamps NO
# `healthy_since` and touches NO probe counters — so it can never
# masquerade as probe-verified recovery health. The distinction is
# enforced at the consumption point by rs_probe_qualified: only a
# canary streak that crossed the threshold is failback-qualified.
rs_mark_success() {
    rs_apply "$1" '.profiles[$p] = ((.profiles[$p] // {}) + {state:"healthy",
                                    reason:"attempt succeeded",
                                    until:null, last_success_at:$__now})' --arg p "$2"
}

# ── probe scheduling + evidence (#257 D T1; plan decisions 1 + 3) ────
# THREE distinct concepts, never conflated:
#   scheduling  next_probe_at        (when a probe is due)
#   execution   probe_due | probing  (the in-flight marker — an
#                                    in-flight probe is NOT a health
#                                    claim and NOT a degradation)
#   evidence    consecutive_probe_successes, healthy_since,
#               last_probe_at, probe_generation
# The marker never changes eligibility ranking by itself; the read
# side (rs_effective_*) resolves what a marker MEANS.

# rs_schedule_probe <attempt_id> <profile> <next-probe-at-epoch> <reason>
# Sets the SCHEDULING field and the probe_due execution marker
# without touching evidence counters.
rs_schedule_probe() {
    local id="$1" p="$2" at="$3" why="${4:-scheduled}"
    rs_apply "$id" \
        '.profiles[$p] = ((.profiles[$p] // {}) + {state:"probe_due",
                          reason:$why, until:null,
                          next_probe_at:($at|tonumber)})' \
        --arg p "$p" --arg at "$at" --arg why "$why"
}

# rs_probe_begin <attempt_id> <profile> <generation>
# Marks a probe IN FLIGHT. Crash-visible by design: if the prober
# dies here the marker persists and the read side treats it as
# ABANDONED (absence of evidence), never as failure or health.
rs_probe_begin() {
    local id="$1" p="$2" gen="$3"
    rs_apply "$id" \
        '.profiles[$p] = ((.profiles[$p] // {}) + {state:"probing",
                          reason:"probe in flight", until:null,
                          probe_generation:($gen|tonumber),
                          probe_started_at:$__now})' \
        --arg p "$p" --arg gen "$gen"
}

# rs_probe_pass <attempt_id> <profile> <threshold>
# REAL positive canary evidence: increments the success counter and
# promotes to `healthy` ONLY when the counter reaches the threshold —
# the sole evidence-backed edge into health.
rs_probe_pass() {
    local id="$1" p="$2" threshold="$3"
    rs_apply "$id" \
        '.profiles[$p] = ((.profiles[$p] // {}) as $e
          | (($e.consecutive_probe_successes // 0) + 1) as $n
          | $e + {consecutive_probe_successes:$n, last_probe_at:$__now,
                  next_probe_at:null, probe_generation:null,
                  state:(if $n >= ($t|tonumber) then "healthy" else "probe_due" end),
                  reason:(if $n >= ($t|tonumber)
                          then "probe-verified healthy (" + ($n|tostring) + "/" + $t + " successes)"
                          else "probe passed (" + ($n|tostring) + "/" + $t + ") — threshold not reached"
                          end),
                  until:null,
                  healthy_since:(if $n >= ($t|tonumber)
                                 then ($e.healthy_since // $__now)
                                 else null end)})' \
        --arg p "$p" --arg t "$threshold"
}

# rs_probe_fail <attempt_id> <profile> <next-probe-at-epoch> <reason>
# REAL negative canary evidence: resets the success streak and
# reschedules. Never called for an abandoned probe.
rs_probe_fail() {
    local id="$1" p="$2" at="$3" why="${4:-probe failed}"
    rs_apply "$id" \
        '.profiles[$p] = ((.profiles[$p] // {}) + {state:"cooldown",
                          reason:$why, until:($at|tonumber),
                          consecutive_probe_successes:0,
                          last_probe_at:$__now, healthy_since:null,
                          probe_generation:null,
                          next_probe_at:($at|tonumber)})' \
        --arg p "$p" --arg at "$at" --arg why "$why"
}

# rs_probe_abandon <attempt_id> <profile> <next-probe-at-epoch>
# ABSENCE of evidence (a prober died mid-flight): clears the
# in-flight marker to `unknown`, reschedules, and leaves EVERY
# evidence counter untouched — a supervisor crash is never
# attributed to the provider, and abandonment never yields health.
rs_probe_abandon() {
    local id="$1" p="$2" at="$3"
    rs_apply "$id" \
        '.profiles[$p] = ((.profiles[$p] // {}) + {state:"unknown",
                          reason:"probe abandoned (prober did not record evidence) — rescheduled; no provider evidence inferred",
                          until:null, probe_generation:null,
                          next_probe_at:($at|tonumber)})' \
        --arg p "$p" --arg at "$at"
}

# ── effective state (read-side decay; pool outranks profile) ─────────
# rs_effective_state <profile> <pool> -> one word:
#   pool-blocked states win; a passed `until` reads as unknown (decay —
#   NEVER healthy; the caller journals the decay); `disabled` has no
#   until and never decays.
#
# D (#257 T1) extends the read side with THREE additional rules,
# each resolving what a stored word MEANS without changing B's:
#   ABANDONED  a `probing` marker older than RS_PROBE_ABANDON_SEC is
#              absence of evidence: it reads as `unknown` (never
#              `probe_fail`, never `healthy`). The marker itself is
#              an execution state, never a degradation.
#   DWELL      `healthy` is a probe-verified claim with a shelf life:
#              once `healthy_since` is older than RS_HEALTHY_TTL_SEC
#              it decays to `unknown` like any expiry.
#   MARKERS    `probe_due` and `probing` are not selectable states;
#              they surface as themselves so callers can journal the
#              reason rather than mistake them for availability.
RS_PROBE_ABANDON_SEC="${CCT_ROUTING_PROBE_ABANDON_SEC:-900}"
RS_HEALTHY_TTL_SEC="${CCT_ROUTING_HEALTHY_TTL_SEC:-86400}"

# THE shared resolution program (one definition; both accessors use
# it so the state word and the (state, until) pair can never drift).
_rs_eff_prog='
    def eff(e):
        if e == null then {state:"unknown", until:null}
        elif (e.state == "probing"
              and ((e.probe_started_at // 0) + $abandon) <= $now)
            then {state:"unknown", until:null}
        elif (e.state == "healthy" and e.healthy_since != null
              and (e.healthy_since + $ttl) <= $now)
            then {state:"unknown", until:null}
        elif (e.until != null and e.until <= $now) then {state:"unknown", until:null}
        else {state:e.state, until:e.until} end;
    (eff(.pools[$pool])) as $ps
    | (if $ps.state != "unknown" and $ps.state != "healthy"
       then {state:("pool:" + $ps.state), until:$ps.until}
       else eff(.profiles[$p]) end) as $g'

rs_effective_state() {
    local p="$1" pool="$2" doc
    doc=$(rs_read) || return $?
    jq -r --arg p "$p" --arg pool "$pool" --argjson now "$(rs_now)" \
          --argjson abandon "$RS_PROBE_ABANDON_SEC" --argjson ttl "$RS_HEALTHY_TTL_SEC" \
          "$_rs_eff_prog | \$g.state" <<< "$doc"
}

# rs_effective_info <profile> <pool> -> "<state>\t<until|->"
# The same read-side decay and pool precedence as rs_effective_state,
# plus the GOVERNING entry's remaining `until` (- when none — e.g.
# disabled, which has no re-eligibility time). Selection uses the
# until to compute the earliest re-eligibility instant (FR-B8).
rs_effective_info() {
    local p="$1" pool="$2" doc
    doc=$(rs_read) || return $?
    jq -r --arg p "$p" --arg pool "$pool" --argjson now "$(rs_now)" \
          --argjson abandon "$RS_PROBE_ABANDON_SEC" --argjson ttl "$RS_HEALTHY_TTL_SEC" \
          "$_rs_eff_prog | \"\\(\$g.state)\\t\\(\$g.until // \"-\")\"" <<< "$doc"
}

# rs_probe_evidence <profile> -> "<successes>\t<healthy_since|->\t<next_probe_at|->\t<generation|->"
# EVIDENCE only — never a state claim. Failback (T4) reads this
# beside the effective state so the consumption point can apply
# threshold + dwell without the store encoding policy.
rs_probe_evidence() {
    local p="$1" doc
    doc=$(rs_read) || return $?
    jq -r --arg p "$p" '
        (.profiles[$p] // {}) as $e
        | "\($e.consecutive_probe_successes // 0)\t\($e.healthy_since // "-")\t\($e.next_probe_at // "-")\t\($e.probe_generation // "-")"' <<< "$doc"
}

# rs_probe_qualified <profile> <threshold> -> rc 0 iff the profile
# carries PROBE-VERIFIED health: state healthy AND a stamped
# healthy_since (the threshold-crossing instant) AND a canary streak
# at or above the threshold. THE predicate failback (T4) consumes —
# `state == "healthy"` alone is never failback-qualified, so B's
# execution-evidence health can never trigger a D failback.
rs_probe_qualified() {
    local p="$1" t="$2" doc
    doc=$(rs_read) || return $?
    jq -e --arg p "$p" --argjson t "$t" '
        (.profiles[$p] // {}) as $e
        | ($e.state == "healthy")
          and ($e.healthy_since != null)
          and (($e.consecutive_probe_successes // 0) >= $t)' >/dev/null 2>&1 <<< "$doc"
}

# rs_due_probes <now-epoch> -> one profile id per line whose
# next_probe_at is due, PLUS profiles whose in-flight marker is
# abandoned (the tick reconciles those first). Scheduling query
# only — it makes no health claim.
rs_due_probes() {
    local now="${1:-$(rs_now)}" doc
    doc=$(rs_read) || return $?
    jq -r --argjson now "$now" --argjson abandon "$RS_PROBE_ABANDON_SEC" '
        .profiles | to_entries[]
        | select((.value.next_probe_at != null and .value.next_probe_at <= $now)
                 or (.value.state == "probing"
                     and ((.value.probe_started_at // 0) + $abandon) <= $now))
        | .key' <<< "$doc"
}
