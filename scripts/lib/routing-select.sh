#!/usr/bin/env bash
# routing-select.sh — deterministic Tier-1 selection (#251 T3,
# increment B of #109; plan decisions 2 + 4, FR-B4/FR-B8).
#
# A PURE function over three inputs: increment A's effective policy
# (rc_effective output), the attempt-local attempted set, and T1's
# circuit state (read-only, via rs_effective_info). It writes nothing
# and launches nothing — the supervisor executes its output.
#
# Filter order (every candidate receives a journaled verdict in
# explain's vocabulary; selection is BOUNDED and CYCLE-FREE by
# construction — the attempted set means a profile is offered at most
# once per unit per eligibility window):
#   1. effective policy disabled        -> everything rejected
#   2. tier: B is tier1-ONLY            -> tier2 never selected
#   3. role: must hold "build"
#   4. attempted set (attempt-local)    -> already tried/incompatible
#   5. circuit state: disabled/cooldown and D's recovery markers ->
#      blocked (pool outranks profile via rs_effective_info); unknown is ELIGIBLE but
#      journaled "never treated as healthy" — B has no probes, and a
#      never-run profile must be reachable.
# Candidates are considered in a TOTAL order: tier -> priority ASC ->
# profile id lexical ASC. The id tie-break is POLICY, not an accident
# of declaration/JSON order — reordering a registry must never change
# which backend is selected (the id is unique within a validated
# registry and gives predictable explain/journal output).
#
# Output — exactly THREE mutually exclusive shapes (T4 consumes them
# without inventing precedence; a non-null terminal_reason MEANS the
# supervisor may park/terminate for it, never "zero candidates at this
# instant"):
#   1. selected:  selected!=null, exhausted=false,
#                 earliest_retry=null, terminal_reason=null
#                 (a selected state carries NO sleep target)
#   2. TEMPORARY exhaustion: selected=null, exhausted=true,
#                 earliest_retry=<min governing until>,
#                 terminal_reason=null  (FR-B8: sleep, then reselect)
#   3. PERMANENT exhaustion: selected=null, exhausted=true,
#                 earliest_retry=null,
#                 terminal_reason="routing_no_eligible_profile"
# selected is NAMED fields (the tuple stays an opaque primitive);
# considered[] is EVERY candidate's explain-vocabulary verdict —
# EVIDENCE ONLY: T4 must never recompute eligibility from it;
# selected/earliest_retry/terminal_reason are the authoritative
# outputs.

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/routing-state.sh"
# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/routing-actions.sh"

# Increment C (#254 T3, plan decision 8): rt_select gains an OPTIONAL
# route-class argument. ABSENT (or tier1_only) reproduces increment
# B's behavior exactly — the unmodified B suite is the compatibility
# gate. A route class only REMOVES candidates or restructures TIER
# precedence per the frozen decision; within a tier, the total order
# (priority ASC -> id lexical ASC) is never reordered. The three
# output shapes are unchanged. tier2_fallback's unlock predicate is
# pinned to the shapes themselves: a tier1 pass that ends TEMPORARY
# (earliest set) waits — only the permanent shape (no selection, no
# earliest) unlocks tier2. Terminal outcomes from actual attempts
# (denied/unknown/identity/independence/crash) are handled ABOVE this
# oracle by the action table and never re-enter selection as a
# fallback opportunity.
rt_select() {  # <effective-json> <attempted-json-array> [role] [route-class] [min-context-tokens]
    local eff="$1" attempted="${2:-[]}" role="${3:-build}" rclass="${4:-}" minctx="${5:-}"
    if [[ -n "$minctx" ]] && ! [[ "$minctx" =~ ^[1-9][0-9]*$ ]]; then
        echo "routing-select: min_context_tokens must be a positive integer (got '$minctx')" >&2
        return 1
    fi
    case "$rclass" in
        ""|tier1_only|primary_only|tier2_fallback|tier2_preferred) ;;
        *)
            echo "routing-select: route class '$rclass' is not in the closed vocabulary (primary_only tier1_only tier2_fallback tier2_preferred)" >&2
            return 1
            ;;
    esac
    local enabled considered="[]" selected="null" earliest="null"
    enabled=$(jq -r '.enabled' <<< "$eff")

    _consider() {  # id verdict reason
        considered=$(jq -c --arg id "$1" --arg v "$2" --arg r "$3" \
            '. + [{id:$id, verdict:$v, reason:$r}]' <<< "$considered")
    }

    # THE candidate evaluator — one body for every route class, so the
    # filter semantics (policy, role, attempted set, circuit state)
    # cannot drift between B's path and C's. Only membership and tier
    # precedence differ per class; this body never does.
    local c id tier priority pool state until
    _rt_eval() {  # <tuple-line>
        c="$1"
        id=$(jq -r '.[0]' <<< "$c"); tier=$(jq -r '.[4]' <<< "$c")
        priority=$(jq -r '.[5]' <<< "$c"); pool=$(jq -r '.[6]' <<< "$c")
        if [[ "$enabled" != "true" ]]; then
            _consider "$id" rejected "routing is disabled by the effective policy"
            return 0
        fi
        if ! jq -e --arg r "$role" '.[7] | index($r) != null' >/dev/null 2>&1 <<< "$c"; then
            _consider "$id" rejected "does not hold role '$role'"
            return 0
        fi
        # context capability (#109 increment F, §5 step 4). Runs ONLY
        # when the task states a requirement, so an absent
        # min_context_tokens leaves this ladder byte-identical to
        # pre-F behavior.
        #
        # The effective limit is min(declared, applicable observed),
        # and an observation may only NARROW the declaration — never
        # broaden it (FR-F5). Crucially, an observation is an UPPER
        # BOUND seen while FAILING, not a proof of capacity (FR-F6):
        # with no declaration there is nothing to narrow, so the
        # profile stays UNKNOWN and is refused. Treating a bare
        # observation as the effective limit would let an overflow
        # FAILURE promote an undeclared profile into eligibility.
        if [[ -n "$minctx" ]]; then
            local declared observed effective src
            declared=$(jq -r --arg id "$id" '(.context_limits // {})[$id] // empty' <<< "$eff")
            if [[ -z "$declared" ]]; then
                _consider "$id" rejected "task requires ${minctx} tokens of context; profile declares no context_limit — capacity is unproven, and an unproven capacity is never a grant"
                return 0
            fi
            effective="$declared"; src="declared"
            local dg
            dg=$(jq -r --arg id "$id" '(.identities // {})[$id] // empty' <<< "$eff")
            if [[ -n "$dg" ]]; then
                # FAIL CLOSED: an unreadable or malformed observation
                # store must refuse, never fall back to the declared
                # limit — that fallback would discard a proven narrower
                # cap and widen eligibility (FR-F5).
                observed=$(rs_observed_context_limit "$dg") || {
                    echo "routing-select: refusing to select against an unreadable observation store — the declared limit is not a safe fallback for a cap that may already be proven narrower" >&2
                    return 1
                }
                if [[ -n "$observed" && "$observed" -lt "$effective" ]]; then
                    effective="$observed"; src="observed (declared ${declared}, narrowed by an upper bound seen from this exact execution identity)"
                fi
            fi
            if [[ "$effective" -lt "$minctx" ]]; then
                _consider "$id" rejected "task requires ${minctx} tokens of context; effective limit is ${effective} [${src}]"
                return 0
            fi
        fi
        if jq -e --arg id "$id" 'index($id) != null' >/dev/null 2>&1 <<< "$attempted"; then
            _consider "$id" rejected "already attempted or incompatible in this unit"
            return 0
        fi
        local info
        info=$(rs_effective_info "$id" "$pool") || return $?
        state="${info%%$'\t'*}"; until="${info##*$'\t'}"
        case "$state" in
            disabled|pool:disabled)
                _consider "$id" rejected "disabled (auth) — no automatic re-eligibility in increment B" ;;
            cooldown|pool:cooldown)
                _consider "$id" rejected "cooling until $until (${state})"
                if [[ "$until" != "-" ]]; then
                    earliest=$(jq -n --argjson e "$earliest" --argjson u "$until" \
                        'if $e == null or $u < $e then $u else $e end')
                fi
                ;;
            degraded|probe_due|probing|pool:degraded|pool:probe_due|pool:probing)
                _consider "$id" rejected "recovery state '$state' is not selectable until a canary is probe-qualified healthy" ;;
            *)
                if [[ "$selected" == "null" ]]; then
                    selected=$(jq -c '{id:.[0], backend:.[1], provider:.[2], model:.[3],
                                       tier:.[4], priority:.[5], pool:.[6], roles:.[7],
                                       tool_profile:.[8], data_policy:.[9],
                                       credential_ref:.[10], endpoint_ref:.[11]}' <<< "$c")
                    _consider "$id" selected "eligible in $tier at priority $priority (state: $state$( [[ "$state" == "unknown" ]] && printf '%s' " — never treated as healthy" ))"
                else
                    _consider "$id" eligible "eligible at priority $priority, a higher-priority profile was selected"
                fi
                ;;
        esac
        return 0
    }

    # per-tier total order: priority ASC -> id lexical ASC. The id
    # tie-break is POLICY (reordering a registry must never change the
    # selection). jq -c emits one tuple per line.
    local t1_order t2_order rest
    t1_order=$(jq -c '[.candidates[] | select(.[4] == "tier1")] | sort_by([.[5], .[0]]) | .[]' <<< "$eff")
    t2_order=$(jq -c '[.candidates[] | select(.[4] == "tier2")] | sort_by([.[5], .[0]]) | .[]' <<< "$eff")
    rest=$(jq -c '.candidates[] | select(.[4] != "tier1")' <<< "$eff")

    case "$rclass" in
    ""|tier1_only)
        # increment B, verbatim: tier1 in order, everything else is
        # never reached
        while IFS= read -r c; do
            [[ -z "$c" ]] && continue
            _rt_eval "$c" || return $?
        done <<< "$t1_order"
        while IFS= read -r c; do
            [[ -z "$c" ]] && continue
            id=$(jq -r '.[0]' <<< "$c"); tier=$(jq -r '.[4]' <<< "$c")
            _consider "$id" rejected "increment B routes tier1 only — $tier is never selected (Tier-2 selection is increment C)"
        done <<< "$rest"
        ;;
    primary_only)
        # only the total-order-first tier1 candidate is admissible;
        # the primary is a property of the DECLARED order, not of
        # state (a cooling primary means wait, never "next best")
        local primary
        primary=$(jq -r '[.candidates[] | select(.[4] == "tier1")] | sort_by([.[5], .[0]]) | (.[0][0] // "")' <<< "$eff")
        while IFS= read -r c; do
            [[ -z "$c" ]] && continue
            id=$(jq -r '.[0]' <<< "$c")
            if [[ "$id" != "$primary" ]]; then
                _consider "$id" rejected "route class 'primary_only' admits only the primary candidate '$primary'"
                continue
            fi
            _rt_eval "$c" || return $?
        done <<< "$t1_order"
        while IFS= read -r c; do
            [[ -z "$c" ]] && continue
            id=$(jq -r '.[0]' <<< "$c"); tier=$(jq -r '.[4]' <<< "$c")
            _consider "$id" rejected "route class 'primary_only' never reaches $tier"
        done <<< "$rest"
        ;;
    tier2_fallback)
        # tier1 exactly as B; tier2 unlocks ONLY on the permanent-
        # exhaustion shape of that pass (no selection AND no earliest)
        # AND only when the effective policy permits tier2 delegation
        # (#254 T6 repo restriction — defense in depth beside the
        # supervisor's early refusal)
        local t2ok
        t2ok=$(jq -r 'if .tier2_delegation_allowed == null then true else .tier2_delegation_allowed end' <<< "$eff")
        while IFS= read -r c; do
            [[ -z "$c" ]] && continue
            _rt_eval "$c" || return $?
        done <<< "$t1_order"
        if [[ "$t2ok" == "false" ]]; then
            while IFS= read -r c; do
                [[ -z "$c" ]] && continue
                id=$(jq -r '.[0]' <<< "$c")
                _consider "$id" rejected "tier2 delegation is forbidden by repository policy (routing.tier2.delegation_enabled = false)"
            done <<< "$t2_order"
        elif [[ "$selected" == "null" && "$earliest" == "null" ]]; then
            while IFS= read -r c; do
                [[ -z "$c" ]] && continue
                _rt_eval "$c" || return $?
            done <<< "$t2_order"
        else
            while IFS= read -r c; do
                [[ -z "$c" ]] && continue
                id=$(jq -r '.[0]' <<< "$c")
                _consider "$id" rejected "tier2 locked — tier1 is not permanently exhausted (route class 'tier2_fallback' waits; the tier requirement is never weakened)"
            done <<< "$t2_order"
        fi
        ;;
    tier2_preferred)
        # tier2 first by policy, tier1 as fallback; within each tier
        # the order is untouched. The repo tier2 restriction (#254 T6)
        # locks the tier2 pass entirely.
        local t2ok2
        t2ok2=$(jq -r 'if .tier2_delegation_allowed == null then true else .tier2_delegation_allowed end' <<< "$eff")
        if [[ "$t2ok2" == "false" ]]; then
            while IFS= read -r c; do
                [[ -z "$c" ]] && continue
                id=$(jq -r '.[0]' <<< "$c")
                _consider "$id" rejected "tier2 delegation is forbidden by repository policy (routing.tier2.delegation_enabled = false)"
            done <<< "$t2_order"
        else
            while IFS= read -r c; do
                [[ -z "$c" ]] && continue
                _rt_eval "$c" || return $?
            done <<< "$t2_order"
        fi
        while IFS= read -r c; do
            [[ -z "$c" ]] && continue
            _rt_eval "$c" || return $?
        done <<< "$t1_order"
        ;;
    esac

    local exhausted=false term="null"
    if [[ "$selected" == "null" ]]; then
        exhausted=true
        if [[ "$earliest" == "null" ]]; then
            # PERMANENT exhaustion — the only state that carries a
            # terminal reason. The closed-enum discipline applies to
            # EVERY emitter, not only ra_decide: validate first.
            ra_terminal_valid routing_no_eligible_profile || {
                echo "routing-select: exhaustion reason is not in the closed enum" >&2
                return 1
            }
            term='"routing_no_eligible_profile"'
        fi
        # TEMPORARY exhaustion (earliest set): terminal_reason stays
        # null — a future re-eligibility instant is not a terminal
        # disposition.
    else
        # a selected state carries no sleep target
        earliest="null"
    fi
    jq -n --argjson selected "$selected" --argjson considered "$considered" \
          --argjson exhausted "$exhausted" --argjson earliest "$earliest" \
          --argjson term "$term" \
          '{selected:$selected, considered:$considered, exhausted:$exhausted,
            earliest_retry:$earliest, terminal_reason:$term}'
}
