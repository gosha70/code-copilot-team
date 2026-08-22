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

# Convenience mutations (all through rs_apply's idempotency):
# rs_set_profile <attempt_id> <profile> <state> <reason> <until-epoch|->
rs_set_profile() {
    local id="$1" p="$2" st="$3" why="$4" until="${5:--}"
    rs_apply "$id" \
        '.profiles[$p] = {state:$st, reason:$why,
                          until:(if $until == "-" then null else ($until|tonumber) end),
                          failed_at:$__now}' \
        --arg p "$p" --arg st "$st" --arg why "$why" --arg until "$until"
}
# rs_set_pool <attempt_id> <pool> <state> <reason> <until-epoch|->
rs_set_pool() {
    local id="$1" pool="$2" st="$3" why="$4" until="${5:--}"
    rs_apply "$id" \
        '.pools[$pool] = {state:$st, reason:$why,
                          until:(if $until == "-" then null else ($until|tonumber) end),
                          failed_at:$__now}' \
        --arg pool "$pool" --arg st "$st" --arg why "$why" --arg until "$until"
}
# rs_mark_success <attempt_id> <profile>
rs_mark_success() {
    rs_apply "$1" '.profiles[$p] = {state:"healthy", reason:"attempt succeeded",
                                    until:null, last_success_at:$__now}' --arg p "$2"
}

# ── effective state (read-side decay; pool outranks profile) ─────────
# rs_effective_state <profile> <pool> -> one word:
#   pool-blocked states win; a passed `until` reads as unknown (decay —
#   NEVER healthy; the caller journals the decay); `disabled` has no
#   until and never decays.
rs_effective_state() {
    local p="$1" pool="$2" doc
    doc=$(rs_read) || return $?
    jq -r --arg p "$p" --arg pool "$pool" --argjson now "$(rs_now)" '
        def eff(e): if e == null then "unknown"
            elif (e.until != null and e.until <= $now) then "unknown"
            else e.state end;
        (eff(.pools[$pool])) as $ps
        | if $ps != "unknown" and $ps != "healthy" then "pool:" + $ps
          else eff(.profiles[$p]) end' <<< "$doc"
}

# rs_effective_info <profile> <pool> -> "<state>\t<until|->"
# The same read-side decay and pool precedence as rs_effective_state,
# plus the GOVERNING entry's remaining `until` (- when none — e.g.
# disabled, which has no re-eligibility time). Selection uses the
# until to compute the earliest re-eligibility instant (FR-B8).
rs_effective_info() {
    local p="$1" pool="$2" doc
    doc=$(rs_read) || return $?
    jq -r --arg p "$p" --arg pool "$pool" --argjson now "$(rs_now)" '
        def eff(e): if e == null then {state:"unknown", until:null}
            elif (e.until != null and e.until <= $now) then {state:"unknown", until:null}
            else {state:e.state, until:e.until} end;
        (eff(.pools[$pool])) as $ps
        | (if $ps.state != "unknown" and $ps.state != "healthy"
           then {state:("pool:" + $ps.state), until:$ps.until}
           else eff(.profiles[$p]) end) as $g
        | "\($g.state)\t\($g.until // "-")"' <<< "$doc"
}
