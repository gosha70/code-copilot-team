#!/usr/bin/env bash
# routing-recovery.sh — recovery timing: when the next probe is due
# (#257, increment D of #109, T1; plan decision 3).
#
# THE precedence chain (umbrella §8), highest-confidence evidence
# first — a computed backoff is the LAST resort, never an override of
# what the provider actually told us:
#   1. provider-supplied reset time      (reset_at)
#   2. Retry-After                       (retry_after_sec)
#   3. subscription rate_limits.*.resets_at
#   4. bounded exponential backoff WITH jitter
#
# Backoff numerics are NAMED IMPLEMENTATION DEFAULTS journaled
# whenever applied — not configuration and not compatibility surface
# (a knob, if ever wanted, takes the refused->implemented->tested
# promotion path). Jitter is DETERMINISTIC: derived from a hash of
# profile id + failure count, so a test can assert an exact instant
# and two probers computing the same schedule agree. Wall-clock
# randomness would make the schedule unreproducible and untestable.
#
# bash 3.2; jq + shasum only.

RD_BACKOFF_BASE_SEC="${RD_BACKOFF_BASE_SEC:-60}"
RD_BACKOFF_MAX_SEC="${RD_BACKOFF_MAX_SEC:-3600}"
RD_JITTER_PCT="${RD_JITTER_PCT:-20}"

# The closed source vocabulary — every schedule says WHERE its
# instant came from, so a journal line is auditable evidence rather
# than an opaque number.
RD_SOURCES="reset_at retry_after rate_limits backoff"

rd_source_valid() { [[ " $RD_SOURCES " == *" $1 "* ]]; }

# rd_jitter_offset <profile-id> <failure-count> <window-sec>
# Deterministic signed offset within ±RD_JITTER_PCT of the window.
# Same inputs -> same offset, on any host, in any process.
rd_jitter_offset() {
    local id="$1" n="$2" window="$3" hex dec span
    hex=$(printf '%s:%s' "$id" "$n" | { command -v shasum >/dev/null 2>&1 && shasum -a 256 || sha256sum; } | cut -c1-8)
    dec=$((16#$hex))
    span=$(( window * RD_JITTER_PCT / 100 ))
    [[ "$span" -le 0 ]] && { echo 0; return 0; }
    # map the digest onto [-span, +span]
    echo $(( (dec % ((2 * span) + 1)) - span ))
}

# rd_backoff_window <failure-count> -> bounded exponential window
rd_backoff_window() {
    local n="${1:-1}" w="$RD_BACKOFF_BASE_SEC" i=1
    [[ "$n" -lt 1 ]] && n=1
    while [[ "$i" -lt "$n" ]]; do
        w=$(( w * 2 ))
        if [[ "$w" -ge "$RD_BACKOFF_MAX_SEC" ]]; then w="$RD_BACKOFF_MAX_SEC"; break; fi
        i=$(( i + 1 ))
    done
    echo "$w"
}

# rd_next_probe_at <now-epoch> <profile-id> <failure-count> <evidence-json>
# -> "<epoch>\t<source>\t<detail>"
# evidence-json is the normalized result's evidence object; absent or
# malformed fields simply fall through the chain (never fail closed
# into "probe immediately" — an unknown schedule uses backoff).
rd_next_probe_at() {
    local now="$1" id="$2" n="$3" ev="${4:-{\}}"
    local v

    v=$(jq -r 'if type == "object" then (.reset_at // empty) else empty end' <<< "$ev" 2>/dev/null || true)
    if [[ -n "$v" ]]; then
        local epoch
        epoch=$(rd_iso_to_epoch "$v") || epoch=""
        if [[ -n "$epoch" && "$epoch" -gt "$now" ]]; then
            printf '%s\t%s\t%s\n' "$epoch" "reset_at" "provider-supplied reset time $v"
            return 0
        fi
    fi

    v=$(jq -r 'if type == "object" then (.retry_after_sec // empty) else empty end' <<< "$ev" 2>/dev/null || true)
    if [[ "$v" =~ ^[0-9]+$ && "$v" -gt 0 ]]; then
        printf '%s\t%s\t%s\n' "$(( now + v ))" "retry_after" "Retry-After ${v}s"
        return 0
    fi

    v=$(jq -r 'if type == "object" then (.rate_limits_resets_at // empty) else empty end' <<< "$ev" 2>/dev/null || true)
    if [[ -n "$v" ]]; then
        local epoch
        epoch=$(rd_iso_to_epoch "$v") || epoch=""
        if [[ -n "$epoch" && "$epoch" -gt "$now" ]]; then
            printf '%s\t%s\t%s\n' "$epoch" "rate_limits" "subscription rate_limits resets_at $v"
            return 0
        fi
    fi

    local window offset at
    window=$(rd_backoff_window "$n")
    offset=$(rd_jitter_offset "$id" "$n" "$window")
    at=$(( now + window + offset ))
    [[ "$at" -le "$now" ]] && at=$(( now + 1 ))
    printf '%s\t%s\t%s\n' "$at" "backoff" \
        "bounded exponential backoff (RD_BACKOFF_BASE_SEC=$RD_BACKOFF_BASE_SEC, RD_BACKOFF_MAX_SEC=$RD_BACKOFF_MAX_SEC) window ${window}s with deterministic jitter ${offset}s (RD_JITTER_PCT=$RD_JITTER_PCT) — named implementation defaults"
    return 0
}

# rd_iso_to_epoch <iso8601> — host-portable (macOS + GNU date).
rd_iso_to_epoch() {
    local s="$1"
    [[ "$s" =~ ^[0-9]+$ ]] && { echo "$s"; return 0; }
    date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$s" +%s 2>/dev/null && return 0
    date -u -d "$s" +%s 2>/dev/null && return 0
    return 1
}
