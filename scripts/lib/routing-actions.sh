#!/usr/bin/env bash
# routing-actions.sh — the class→action policy (#251 T2, increment B
# of #109; plan decision 3's TOTAL normative table).
#
# Maps increment A's frozen nine-cause taxonomy to supervisor
# decisions. Cause (A's observation), action (B's response), and
# terminal reason (why the supervisor finally refused/parked) are
# three different things:
#   - the table below is TOTAL — every cause has scope, durable state
#     effect, same-profile retry cardinality, next-selection rule, and
#     terminal reason; nothing here may invent a fallback the table
#     does not name;
#   - the RA_*_SEC values are named IMPLEMENTATION DEFAULTS, not
#     compatibility or configuration surface (retunable from observed
#     provider behavior without a spec revision; a config knob would
#     take the refused→implemented→tested promotion path);
#   - RA_TERMINAL_REASONS is a CLOSED machine-readable enum defined
#     ONCE, here. No call site may assemble a reason dynamically —
#     a new A failure class must never silently create a new B park
#     reason. The journal carries richer text BESIDE the enum value.

# Implementation-default timings (seconds). Deterministic, tested,
# journaled when applied — not promises.
RA_QUOTA_FALLBACK_COOLDOWN_SEC=3600
RA_RATE_RETRY_DELAY_SEC=60
RA_RATE_COOLDOWN_SEC=120
RA_UNAVAILABLE_RETRY_DELAY_SEC=30
RA_UNAVAILABLE_COOLDOWN_SEC=300

# The CLOSED terminal-reason enum. routing_attempt_indeterminate is
# deliberately distinct from routing_no_eligible_profile: crash
# ambiguity is not "no usable candidates".
RA_TERMINAL_REASONS="routing_pool_exhausted routing_rate_limited routing_provider_unavailable routing_transport_failure routing_auth_failure routing_task_incompatible routing_policy_denied routing_unknown_failure routing_attempt_indeterminate routing_model_identity_mismatch routing_no_eligible_profile"

ra_terminal_valid() {  # <reason> -> 0 iff a member of the closed enum
    local r
    for r in $RA_TERMINAL_REASONS; do [[ "$r" == "$1" ]] && return 0; done
    return 1
}

ra_now() { date -u +%s; }

# ra_iso_to_epoch <iso8601|-> -> epoch on stdout, rc 1 when unparseable
ra_iso_to_epoch() {
    local iso="$1" e=""
    [[ -z "$iso" || "$iso" == "-" || "$iso" == "null" ]] && return 1
    e=$(date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$iso" +%s 2>/dev/null) \
        || e=$(date -u -d "$iso" +%s 2>/dev/null) || true
    [[ "$e" =~ ^[0-9]+$ ]] || return 1
    printf '%s' "$e"
}

# ra_decide <normalized-result-json> <same_profile_retries_so_far> <decision_epoch>
#
# decision_epoch is the DURABLE terminal-result timestamp (decision 5
# step 3) — the temporal basis of every deadline this function emits.
# ra_decide is a PURE function of (result, retries, decision_epoch):
# recomputing the decision after a crash yields byte-identical
# deadlines; the current wall clock may determine how much waiting
# REMAINS (remaining = max(0, not_before - now), computed by the
# supervisor at execution), but never the policy deadline itself.
# A missing/malformed epoch is refused — never silently replaced by
# the wall clock.
#
# Emits ONE decision document:
# {
#   action:   "proceed" | "retry_same" | "failover" | "park" | "breaker",
#   retry_not_before: epoch | null,   # absolute, for retry_same
#   state_op: { kind: "pool_cooldown"|"profile_cooldown"|"profile_disable"|"none",
#               until: epoch|null, reason: text },
#   attempt_local_incompatible: bool, # invalid_request: attempted-set only
#   terminal_reason: <closed enum>|null,
#   journal: text                     # rich text BESIDE the enum
# }
# The SUPERVISOR owns executing the decision (waiting, calling the
# state store with the attempt id, parking).
ra_decide() {
    local result="$1" retries="${2:-0}" epoch="${3:-}"
    if [[ ! "$epoch" =~ ^[0-9]+$ ]]; then
        echo "routing-actions: ra_decide requires the durable decision epoch (got '${epoch:-}') — the wall clock never substitutes for the temporal basis" >&2
        return 1
    fi
    local outcome cause pool profile retry_after reset_at now
    now="$epoch"
    outcome=$(jq -r '.outcome' <<< "$result")
    if [[ "$outcome" == "success" ]]; then
        jq -n '{action:"proceed", retry_not_before:null,
                state_op:{kind:"none", until:null, reason:""},
                attempt_local_incompatible:false, terminal_reason:null,
                journal:"attempt succeeded"}'
        return 0
    fi
    cause=$(jq -r '.failure_class' <<< "$result")
    pool=$(jq -r '.quota_pool' <<< "$result")
    profile=$(jq -r '.profile' <<< "$result")
    retry_after=$(jq -r '.retry_after_sec // empty' <<< "$result")
    reset_at=$(jq -r '.reset_at // empty' <<< "$result")
    _d() {  # action not_before state_kind until reason attempt_local terminal journal
        jq -n --arg action "$1" --argjson nb "$2" \
              --arg kind "$3" --argjson until "$4" --arg sreason "$5" \
              --argjson alocal "$6" --arg term "$7" --arg journal "$8" '
            {action:$action, retry_not_before:$nb,
             state_op:{kind:$kind, until:$until, reason:$sreason},
             attempt_local_incompatible:$alocal,
             terminal_reason:(if $term == "" then null else $term end),
             journal:$journal}'
    }
    _term() {  # closed-enum guard at the ONLY emission point
        ra_terminal_valid "$1" || { echo "routing-actions: '$1' is not in the closed terminal-reason enum" >&2; return 1; }
        printf '%s' "$1"
    }

    case "$cause" in
        quota_exhausted)
            local until reset_epoch journal
            if reset_epoch=$(ra_iso_to_epoch "$reset_at"); then
                until="$reset_epoch"
                journal="pool '$pool' exhausted; cooling to provider reset $reset_at"
            else
                until=$((now + RA_QUOTA_FALLBACK_COOLDOWN_SEC))
                journal="pool '$pool' exhausted; reset evidence absent — bounded fallback cooldown (RA_QUOTA_FALLBACK_COOLDOWN_SEC=${RA_QUOTA_FALLBACK_COOLDOWN_SEC}s)"
            fi
            _d failover null pool_cooldown "$until" "quota exhausted" false \
               "$(_term routing_pool_exhausted)" "$journal"
            ;;
        rate_limited)
            if [[ "$retries" -lt 1 ]]; then
                local delay="${retry_after:-$RA_RATE_RETRY_DELAY_SEC}"
                _d retry_same "$((now + delay))" none null "" false "" \
                   "rate limited; ONE same-profile retry not before epoch+${delay}s ($( [[ -n "$retry_after" ]] && echo "Retry-After" || echo "RA_RATE_RETRY_DELAY_SEC default"))"
            else
                local cd="${retry_after:-$RA_RATE_COOLDOWN_SEC}"
                _d failover null profile_cooldown "$((now + cd))" "rate limited past the retry budget" false \
                   "$(_term routing_rate_limited)" "rate limited after the single retry; profile cooling ${cd}s"
            fi
            ;;
        unavailable|transport)
            local label="provider unavailable" term="routing_provider_unavailable"
            [[ "$cause" == "transport" ]] && { label="transport failure"; term="routing_transport_failure"; }
            if [[ "$retries" -lt 1 ]]; then
                _d retry_same "$((now + RA_UNAVAILABLE_RETRY_DELAY_SEC))" none null "" false "" \
                   "$label; ONE same-profile retry not before epoch+${RA_UNAVAILABLE_RETRY_DELAY_SEC}s (RA_UNAVAILABLE_RETRY_DELAY_SEC)"
            else
                _d failover null profile_cooldown "$((now + RA_UNAVAILABLE_COOLDOWN_SEC))" "$label past the retry budget" false \
                   "$(_term "$term")" "$label after the single retry; profile cooling ${RA_UNAVAILABLE_COOLDOWN_SEC}s (RA_UNAVAILABLE_COOLDOWN_SEC)"
            fi
            ;;
        auth)
            _d failover null profile_disable null "credential or billing rejection" false \
               "$(_term routing_auth_failure)" "auth failure: profile '$profile' DISABLED (no automatic retries; operator action or increment D probes re-enable)"
            ;;
        invalid_request)
            _d failover null none null "" true \
               "$(_term routing_task_incompatible)" "request incompatible with profile '$profile' for THIS unit only — no durable state, no provider penalty"
            ;;
        denied)
            _d park null none null "" false \
               "$(_term routing_policy_denied)" "policy denial — never rerouted around (#190 disposition)"
            ;;
        execution)
            _d breaker null none null "" false "" \
               "task/build failure — not an availability event; the existing breaker path owns disposition"
            ;;
        unknown)
            _d park null none null "" false \
               "$(_term routing_unknown_failure)" "unmatched failure — failing closed: no retry, no failover"
            ;;
        *)
            # The taxonomy is frozen; an unlisted cause is a contract
            # violation upstream. Fail closed exactly like unknown.
            _d park null none null "" false \
               "$(_term routing_unknown_failure)" "unrecognized cause '$cause' (frozen-taxonomy violation upstream) — failing closed"
            ;;
    esac
}
