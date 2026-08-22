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
#   5. circuit state: disabled/cooldown -> blocked (pool outranks
#      profile via rs_effective_info); unknown is ELIGIBLE but
#      journaled "never treated as healthy" — B has no probes, and a
#      never-run profile must be reachable.
# Candidates are considered in a TOTAL order: tier -> priority ASC ->
# profile id lexical ASC. The id tie-break is POLICY, not an accident
# of declaration/JSON order — reordering a registry must never change
# which backend is selected (the id is unique within a validated
# registry and gives predictable explain/journal output).
#
# Output: {
#   selected: {id, backend, provider, model, tier, priority, pool,
#              roles, tool_profile, data_policy, credential_ref,
#              endpoint_ref} | null,       # NAMED fields — the tuple
#                                          # stays an opaque primitive
#   considered: [ {id, verdict: "selected"|"eligible"|"rejected",
#                  reason} ... ],          # EVERY candidate, in order
#   exhausted: bool,
#   earliest_retry: epoch|null,   # min until among time-blocked
#                                 # candidates (FR-B8 sleep target);
#                                 # null when every block is permanent
#   terminal_reason: "routing_no_eligible_profile"|null
# }

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/routing-state.sh"
# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/routing-actions.sh"

rt_select() {  # <effective-json> <attempted-json-array> [role]
    local eff="$1" attempted="${2:-[]}" role="${3:-build}"
    local enabled considered="[]" selected="null" earliest="null" n i
    enabled=$(jq -r '.enabled' <<< "$eff")
    n=$(jq '.candidates | length' <<< "$eff")

    _consider() {  # id verdict reason
        considered=$(jq -c --arg id "$1" --arg v "$2" --arg r "$3" \
            '. + [{id:$id, verdict:$v, reason:$r}]' <<< "$considered")
    }

    # tier1 candidates in priority order, then the never-reached rest.
    # jq -c emits one tuple per line (tuples cannot contain newlines).
    local order rest
    order=$(jq -c '[.candidates[] | select(.[4] == "tier1")] | sort_by([.[5], .[0]]) | .[]' <<< "$eff")
    rest=$(jq -c '.candidates[] | select(.[4] != "tier1")' <<< "$eff")

    local c id tier priority pool state until
    while IFS= read -r c; do
        [[ -z "$c" ]] && continue
        id=$(jq -r '.[0]' <<< "$c"); tier=$(jq -r '.[4]' <<< "$c")
        priority=$(jq -r '.[5]' <<< "$c"); pool=$(jq -r '.[6]' <<< "$c")
        if [[ "$enabled" != "true" ]]; then
            _consider "$id" rejected "routing is disabled by the effective policy"
            continue
        fi
        if ! jq -e --arg r "$role" '.[7] | index($r) != null' >/dev/null 2>&1 <<< "$c"; then
            _consider "$id" rejected "does not hold role '$role'"
            continue
        fi
        if jq -e --arg id "$id" 'index($id) != null' >/dev/null 2>&1 <<< "$attempted"; then
            _consider "$id" rejected "already attempted or incompatible in this unit"
            continue
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
    done <<< "$order"
    while IFS= read -r c; do
        [[ -z "$c" ]] && continue
        id=$(jq -r '.[0]' <<< "$c"); tier=$(jq -r '.[4]' <<< "$c")
        _consider "$id" rejected "increment B routes tier1 only — $tier is never selected (Tier-2 selection is increment C)"
    done <<< "$rest"

    local exhausted=false term="null"
    if [[ "$selected" == "null" ]]; then
        exhausted=true
        # The closed-enum discipline applies to EVERY emitter, not only
        # ra_decide: validate before emitting.
        ra_terminal_valid routing_no_eligible_profile || {
            echo "routing-select: exhaustion reason is not in the closed enum" >&2
            return 1
        }
        term='"routing_no_eligible_profile"'
    fi
    jq -n --argjson selected "$selected" --argjson considered "$considered" \
          --argjson exhausted "$exhausted" --argjson earliest "$earliest" \
          --argjson term "$term" \
          '{selected:$selected, considered:$considered, exhausted:$exhausted,
            earliest_retry:$earliest, terminal_reason:$term}'
}
