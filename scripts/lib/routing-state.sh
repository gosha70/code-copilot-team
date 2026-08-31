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
RS_TICK_LOCK="${CCT_ROUTING_TICK_LOCK:-${RS_FILE}.tick.lock}"
RS_TICK_LOCK_HELD=0

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
    if ! printf '%s\n' "$$" > "${dir}/pid"; then
        rm -rf "$dir" 2>/dev/null || true
        return 2
    fi
}
# rs_trylock -> ACQUIRES the lock or fails immediately (rc 1).
# A NON-BLOCKING acquisition for schedulers: rs_lock deliberately WAITS
# (a supervisor should), but a cron tick must refuse rather than
# pile up behind another writer. The refusal decision and the
# acquisition are THE SAME mkdir — a separate "is it held?" predicate
# followed by a blocking rs_lock would be a TOCTOU that can still
# queue behind a writer that arrives in between.
# A scheduled writer never removes an existing lock. A PID liveness
# check followed by deletion is itself racy: the original owner can
# release and a new writer can acquire between those operations. The
# scheduler fails closed and names the lock for operator recovery.
rs_trylock() {
    local dir="${RS_FILE}.lock"
    mkdir -p "$(dirname "$RS_FILE")" 2>/dev/null || true
    if mkdir "$dir" 2>/dev/null; then
        if ! printf '%s\n' "$$" > "${dir}/pid"; then
            rm -rf "$dir" 2>/dev/null || true
            return 1
        fi
        return 0
    fi
    return 1
}

# The scheduler lock is distinct from the short state-write lock. A tick
# holds this for its complete probe/apply/wake pass, so overlapping cron
# invocations refuse instead of both operating on different snapshots.
rs_tick_trylock() {
    local dir="$RS_TICK_LOCK"
    mkdir -p "$(dirname "$dir")" 2>/dev/null || return 1
    mkdir "$dir" 2>/dev/null || return 1
    if ! printf '%s\n' "$$" > "$dir/pid"; then
        rm -rf "$dir" 2>/dev/null || true
        return 1
    fi
    RS_TICK_LOCK_HELD=1
}

rs_tick_unlock() {
    [[ "$RS_TICK_LOCK_HELD" == "1" ]] || return 0
    if [[ "$(cat "$RS_TICK_LOCK/pid" 2>/dev/null)" != "$$" ]]; then
        echo "routing-state: cannot release scheduler lock $RS_TICK_LOCK because ownership is no longer provable" >&2
        return 1
    fi
    rm -rf "$RS_TICK_LOCK" 2>/dev/null || return 1
    RS_TICK_LOCK_HELD=0
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
        'if .profiles[$p].state == "disabled" and $st != "disabled" then
           error("auth-disabled profiles require rs_operator_enable")
         else .profiles[$p] = ((.profiles[$p] // {}) +
           {state:$st, reason:$why,
            until:(if $until == "-" then null else ($until|tonumber) end),
            failed_at:$__now}
           | if $st == "disabled" then
               . + {next_probe_at:null, probe_generation:null,
                    consecutive_probe_successes:0,
                    consecutive_probe_failures:0, healthy_since:null}
                    + {probe_backoff_attempts:0}
             else . end) end' \
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
    rs_apply "$1" 'if .profiles[$p].state == "disabled" then
                      error("auth-disabled profiles require operator enable")
                    else .profiles[$p] = ((.profiles[$p] // {}) + {state:"healthy",
                                          reason:"attempt succeeded",
                                          until:null, last_success_at:$__now}) end' --arg p "$2"
}

# ── context-limit observations (#109 increment F) ────────────────────
# An observation is keyed by the profile's EXECUTION IDENTITY digest,
# never by its id: the digest changes the moment provider, model,
# endpoint reference, credential reference, backend, tier, pool, roles,
# tool profile or data policy change, so an observation stops applying
# BY CONSTRUCTION when the thing it was observed from no longer exists
# (plan D1/FR-F7). The profile id is stored alongside for readable
# journals and explain output — it is NOT the key.
#
# Observations live under a top-level `observations` object that is
# deliberately ABSENT from rs_read's shape check (plan D5): an existing
# schema_version-1 state file written before F must keep loading, with
# absence meaning "no observations". Adding it to the shape check would
# refuse every live state file on upgrade.
#
# The recorded value is an UPPER BOUND observed while FAILING, never a
# proof of capacity (plan D2). The read side is what enforces that
# distinction; this primitive only stores what was seen.

# rs_record_context_limit <attempt_id> <identity-digest> <profile> <tokens> <evidence>
rs_record_context_limit() {
    local id="$1" digest="$2" profile="$3" tokens="$4" evidence="${5:-invalid_request numeric maximum}"
    [[ "$tokens" =~ ^[1-9][0-9]*$ ]] || {
        echo "routing-state: refusing to record a non-positive context observation ('$tokens') — a vague overflow records nothing" >&2
        return 1
    }
    # MONOTONICALLY NARROWING (FR-F5). A later, LARGER observation must
    # never replace a smaller one: 32768 then 200000 would otherwise
    # broaden eligibility for an identity already proven to cap at
    # 32768. The store keeps the tightest bound ever seen for this
    # identity; a wider later reading is discarded, not averaged and
    # not trusted as "the provider changed" — a provider that really
    # did change is a different endpoint, and FR-F7's identity binding
    # is what expires the old bound.
    rs_apply "$id" \
        '(.observations // {}) as $obs
         | ($obs[$d].context_limit_observed // null) as $prev
         | ($tok | tonumber) as $new
         | if $prev != null and $prev <= $new then .
           else .observations = ($obs + {($d): {context_limit_observed:$new,
                                                profile:$p, evidence:$ev,
                                                observed_at:$__now}})
           end' \
        --arg d "$digest" --arg p "$profile" --arg tok "$tokens" --arg ev "$evidence"
}

# rs_observed_context_limit <identity-digest> — the observed token
# ceiling for THIS execution identity, or empty when none applies.
# Empty is the normal answer, not an error: no observation, a
# different identity, or a pre-F state file all read as "unobserved".
#
# FAILS CLOSED on a malformed store (rc 2). `observations` is optional
# — absence is not an error — but when PRESENT it must be an object of
# well-shaped records. Swallowing a shape error here would silently
# discard a known narrower cap and let selection fall back to the
# operator's (wider) declaration, which is the exact widening FR-F5
# forbids. A caller must never paper over a non-zero return.
rs_observed_context_limit() {
    local doc
    doc=$(rs_read) || return $?
    if jq -e 'has("observations")' >/dev/null 2>&1 <<< "$doc"; then
        if ! jq -e '(.observations | type == "object")
                    and (.observations | to_entries | all(
                          .value | type == "object"
                          and (.context_limit_observed | type == "number")
                          and (.context_limit_observed > 0)))' \
                >/dev/null 2>&1 <<< "$doc"; then
            echo "routing-state: $RS_FILE carries a malformed 'observations' store — refusing to fall back to the declared limit, which would silently widen an already-proven cap" >&2
            return 2
        fi
    fi
    jq -r --arg d "$1" '(.observations // {})[$d].context_limit_observed // empty' <<< "$doc"
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
    if ! rs_apply "$id" \
        'if .profiles[$p].state == "disabled"
         then error("auth-disabled profiles require rs_operator_enable")
         else .profiles[$p] = ((.profiles[$p] // {}) + {state:"probe_due",
                               reason:$why, until:null,
                               next_probe_at:($at|tonumber)}) end' \
        --arg p "$p" --arg at "$at" --arg why "$why"; then
        echo "routing-state: profile '$p' was not scheduled — an auth-disabled profile can exit only through cct routing enable" >&2
        return 1
    fi
}

# rs_schedule_after_cooldown <attempt_id> <profile> <at> <reason>
# Attach D's canary schedule without replacing B's governing cooldown
# before its deadline. At/after `at`, the shared read program surfaces
# probe_due instead of decaying to selectable unknown; before it, B's
# cooldown and earliest-retry behavior remain intact.
rs_schedule_after_cooldown() {
    local id="$1" p="$2" at="$3" why="${4:-recovery canary scheduled}"
    rs_apply "$id" \
        'if .profiles[$p].state == "disabled" then
           error("auth-disabled profiles require rs_operator_enable")
         else .profiles[$p] = ((.profiles[$p] // {}) +
           {next_probe_at:($at|tonumber), probe_schedule_reason:$why}) end' \
        --arg p "$p" --arg at "$at" --arg why "$why"
}

# rs_probe_begin <attempt_id> <profile> <generation>
# Marks a probe IN FLIGHT. Crash-visible by design: if the prober
# dies here the marker persists and the read side treats it as
# ABANDONED (absence of evidence), never as failure or health.
rs_probe_begin() {
    local id="$1" p="$2" gen="$3"
    rs_apply "$id" \
        'if .profiles[$p].state == "disabled" then
           error("auth-disabled profiles require operator enable")
         else .profiles[$p] = ((.profiles[$p] // {}) + {state:"probing",
                               reason:"probe in flight", until:null,
                               next_probe_at:null,
                               probe_generation:($gen|tonumber),
                               probe_started_at:$__now}) end' \
        --arg p "$p" --arg gen "$gen"
}

# rs_probe_pass <attempt_id> <profile> <threshold>
# REAL positive canary evidence: increments the success counter and
# promotes to `healthy` ONLY when the counter reaches the threshold —
# the sole evidence-backed edge into health.
rs_probe_pass() {
    local id="$1" p="$2" threshold="$3"
    rs_apply "$id" \
        'if .profiles[$p].state == "disabled" then
           error("auth-disabled profiles require operator enable")
         else .profiles[$p] = ((.profiles[$p] // {}) as $e
          | (($e.consecutive_probe_successes // 0) + 1) as $n
          | $e + {consecutive_probe_successes:$n, last_probe_at:$__now,
                  consecutive_probe_failures:0,
                  probe_backoff_attempts:0,
                  next_probe_at:(if $n >= ($t|tonumber) then null else $__now end),
                  probe_generation:null,
                  state:(if $n >= ($t|tonumber) then "healthy" else "probe_due" end),
                  reason:(if $n >= ($t|tonumber)
                          then "probe-verified healthy (" + ($n|tostring) + "/" + $t + " successes)"
                          else "probe passed (" + ($n|tostring) + "/" + $t + ") — threshold not reached"
                          end),
                  until:null,
                  healthy_since:(if $n >= ($t|tonumber)
                                 then ($e.healthy_since // $__now)
                                 else null end)}) end' \
        --arg p "$p" --arg t "$threshold"
}

# rs_probe_fail <attempt_id> <profile> <next-probe-at-epoch> <reason>
# REAL negative canary evidence: resets the success streak and
# reschedules. Never called for an abandoned probe.
rs_probe_fail() {
    local id="$1" p="$2" at="$3" why="${4:-probe failed}"
    rs_apply "$id" \
        'if .profiles[$p].state == "disabled" then
           error("auth-disabled profiles require operator enable")
         else .profiles[$p] = ((.profiles[$p] // {}) as $e
          | $e + {state:"cooldown", reason:$why, until:($at|tonumber),
                  consecutive_probe_successes:0,
                  consecutive_probe_failures:(($e.consecutive_probe_failures // 0) + 1),
                  probe_backoff_attempts:(($e.probe_backoff_attempts // 0) + 1),
                  last_probe_at:$__now, healthy_since:null,
                  probe_generation:null,
                  next_probe_at:($at|tonumber)}) end' \
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
        'if .profiles[$p].state == "disabled" then
           error("auth-disabled profiles require operator enable")
         else .profiles[$p] = ((.profiles[$p] // {}) + {state:"unknown",
                          reason:"probe abandoned (prober did not record evidence) — rescheduled; no provider evidence inferred",
                          until:null, probe_generation:null,
                          next_probe_at:($at|tonumber)}) end' \
        --arg p "$p" --arg at "$at"
}

# rs_probe_unverifiable <attempt_id> <profile> <next-epoch> <reason>
# Absence of evidence does not alter provider success/failure streaks,
# but it must advance the scheduling backoff. Reusing rs_probe_abandon
# here left every unverifiable probe permanently on backoff attempt 1.
# A genuinely abandoned in-flight marker still uses rs_probe_abandon
# and touches no counters at all.
rs_probe_unverifiable() {
    local id="$1" p="$2" at="$3" why="${4:-probe unverifiable}"
    rs_apply "$id" \
        'if .profiles[$p].state == "disabled" then
           error("auth-disabled profiles require operator enable")
         else .profiles[$p] = ((.profiles[$p] // {}) as $e
          | $e + {state:"unknown", reason:$why, until:null,
                  probe_generation:null, next_probe_at:($at|tonumber),
                  probe_backoff_attempts:(($e.probe_backoff_attempts // 0) + 1)}) end' \
        --arg p "$p" --arg at "$at" --arg why "$why"
}

# rs_probe_deferred <attempt_id> <profile> <next-epoch> <reason>
# A cap refusal is not provider evidence, but repeatedly reclaiming it
# at the first backoff window pointlessly contends on both scheduler
# locks for the whole accounting window. Advance only the scheduling
# backoff; keep the provider counters untouched and the profile due.
rs_probe_deferred() {
    local id="$1" p="$2" at="$3" why="${4:-probe deferred by caps}"
    rs_apply "$id" \
        'if .profiles[$p].state == "disabled" then
           error("auth-disabled profiles require operator enable")
         else .profiles[$p] = ((.profiles[$p] // {}) as $e
          | $e + {state:"probe_due", reason:$why, until:null,
                  probe_generation:null, next_probe_at:($at|tonumber),
                  probe_backoff_attempts:(($e.probe_backoff_attempts // 0) + 1)}) end' \
        --arg p "$p" --arg at "$at" --arg why "$why"
}

# rs_operator_enable <profile> — the sole exit from auth-disabled.
# Validation and transition share one lock hold; a second invocation sees
# probe_due and refuses instead of manufacturing another operator action.
rs_operator_enable() {
    local p="$1" doc now newdoc rc=0
    rs_lock || return 2
    doc=$(rs_read) || { rc=$?; rs_unlock; return "$rc"; }
    if [[ "$(jq -r --arg p "$p" '.profiles[$p].state // "unknown"' <<< "$doc")" != "disabled" ]]; then
        echo "routing-state: profile '$p' is not auth-disabled — only disabled profiles can be enabled" >&2
        rs_unlock
        return 1
    fi
    now=$(rs_now)
    if ! newdoc=$(jq -ce --arg p "$p" --argjson now "$now" '
        .profiles[$p] = ((.profiles[$p] // {}) +
          {state:"probe_due", reason:"operator re-enabled; canary required",
           until:null, next_probe_at:$now, probe_generation:null,
           consecutive_probe_successes:0, consecutive_probe_failures:0,
           probe_backoff_attempts:0,
           healthy_since:null})
        | .operator_events = ((.operator_events // []) +
          [{at:$now,event:"routing_operator_enable",profile:$p}])' <<< "$doc"); then
        rs_unlock
        return 1
    fi
    _rs_write "$newdoc" || { rs_unlock; return 1; }
    rs_unlock
    rs_journal "routing_operator_enable" "profile '$p' moved disabled -> probe_due; a canary is required before health"
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
        elif (e.next_probe_at != null and e.next_probe_at <= $now)
            then {state:"probe_due", until:e.next_probe_at}
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

# rs_probe_failure_count <profile> -> consecutive verified failures.
# Kept separate from the success evidence tuple so callers cannot repeat
# the old bug of feeding the success streak into exponential backoff.
rs_probe_failure_count() {
    local p="$1" doc
    doc=$(rs_read) || return $?
    jq -r --arg p "$p" '(.profiles[$p].consecutive_probe_failures // 0)' <<< "$doc"
}

# rs_probe_backoff_count <profile> -> scheduling attempts that failed
# to produce recovery. This is deliberately distinct from the provider
# failure counter: unverifiable probes back off without being mislabeled
# as negative provider evidence.
rs_probe_backoff_count() {
    local p="$1" doc
    doc=$(rs_read) || return $?
    jq -r --arg p "$p" '(.profiles[$p].probe_backoff_attempts // 0)' <<< "$doc"
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

# rs_claim_due <now-epoch> -> "<profile>\t<generation>\t<prior>" lines
#
# THE serialization point for concurrent schedulers. Selecting due
# profiles and marking them `probing` is ONE read-select-mark under a
# SINGLE lock hold: the set a caller receives is exactly the set this
# write claimed, so two ticks can never probe the same due event and
# manufacture a success streak out of one recovery.
#   - non-blocking (rs_trylock): a scheduled tick refuses (rc 3)
#     rather than queueing behind another writer;
#   - the claim CONSUMES the schedule: `probing` is set AND
#     next_probe_at is cleared in that same write. Marking alone is
#     not enough — a second tick arriving after the first RELEASED the
#     lock (while it is still out probing) would otherwise re-select
#     the very same due instant. The lock only serializes overlapping
#     ticks; the consumed schedule is what makes a due event
#     single-use. From here only the abandonment window can re-offer
#     the profile, and the probe_* primitives set the next schedule;
#   - generations come from `.probe_seq`, a DURABLE monotonic counter
#     in the store itself. Process-derived ids (pid-based) collide
#     after pid reuse against the permanently-retained idempotency
#     set, silently turning a real transition into a no-op;
#   - `prior` is the pre-claim disposition: `abandoned` for an
#     in-flight marker past its window (the caller reconciles it
#     WITHOUT probing — absence of evidence, never probe_fail), `due`
#     otherwise. Claiming an abandoned entry restarts its abandon
#     window; a tick that then dies simply leaves it abandoned again,
#     so the reconcile converges on the next tick;
#   - nothing due => NO WRITE AT ALL, so an idle tick leaves the
#     store byte-identical.
rs_claim_due() {
    local now="${1:-$(rs_now)}" doc out claims
    rs_trylock || return 3
    doc=$(rs_read) || { local rc=$?; rs_unlock; return "$rc"; }
    if ! out=$(jq -ce --argjson now "$now" --argjson abandon "$RS_PROBE_ABANDON_SEC" '
        ( [ .profiles | to_entries[]
            | select((.value.state != "disabled")
                     and ((.value.next_probe_at != null and .value.next_probe_at <= $now)
                     or (.value.state == "probing"
                         and ((.value.probe_started_at // 0) + $abandon) <= $now)))
            | {id: .key,
               prior: (if .value.state == "probing" then "abandoned" else "due" end)} ]
        ) as $sel
        | (if .probe_seq == null then 0 else .probe_seq end) as $base
        | [ range(0; ($sel | length)) as $i
            | $sel[$i] + {generation: ($base + $i + 1)} ] as $claims
        | { claims: $claims,
            doc: ( reduce $claims[] as $c (.;
                     .profiles[$c.id] = ((.profiles[$c.id] // {})
                       + {state:"probing", reason:"probe claimed by a scheduler tick",
                          until:null, next_probe_at:null,
                          probe_generation:$c.generation,
                          probe_started_at:$now}))
                   | .probe_seq = ($base + ($claims | length)) ) }' <<< "$doc" 2>/dev/null); then
        echo "routing-state: could not evaluate the due-probe claim — nothing written" >&2
        rs_unlock
        return 1
    fi
    claims=$(jq -c '.claims' <<< "$out")
    if [[ "$(jq -r '.claims | length' <<< "$out")" -gt 0 ]]; then
        _rs_write "$(jq -c '.doc' <<< "$out")" || { rs_unlock; return 1; }
    fi
    rs_unlock
    jq -r '.[] | [.id, (.generation|tostring), .prior] | @tsv' <<< "$claims"
}

# rs_due_probes <now-epoch> -> one profile id per line whose
# next_probe_at is due, PLUS profiles whose in-flight marker is
# abandoned (the tick reconciles those first). A READ-ONLY scheduling
# query — it makes no health claim and CLAIMS NOTHING. A scheduler
# that intends to probe must use rs_claim_due; selecting here and
# probing afterwards is the race that lets two ticks share one event.
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
