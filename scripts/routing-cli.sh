#!/usr/bin/env bash
# routing-cli.sh — `cct routing <validate|status|explain>` (#248 T5,
# increment A of #109; plan decision 6).
#
# Three DISTINCT read-only contracts:
#   validate  parse + grammar + schema + semantic validation
#             (registry; then, with --config, the T3 automation
#             validator BEFORE T4 composition — never compose over a
#             config the standalone validator refuses)
#   status    registry/policy state only — per-profile rows; may
#             report credential-env PRESENCE, never contents
#   explain   PURE effective-policy derivation for one route class
#
# None of the three: probes a provider, makes a network call, executes
# anything, writes any state, reads a credential value, or claims what
# a request "would run on". Increment A never writes the state file;
# absent state renders every profile `unknown` — and unknown is NEVER
# treated as healthy. Candidates are rendered as NAMED fields via the
# registry accessors — the canonical tuple is an opaque identity
# primitive for set membership, not a CLI data format.
#
# Exit codes: 0 clean | 1 named violations | 2 usage / not configured.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/routing-config.sh"

REGISTRY="${CCT_ROUTING_REGISTRY:-$HOME/.code-copilot-team/routing.toml}"
STATE="${CCT_ROUTING_STATE:-$HOME/.code-copilot-team/routing-state.json}"
SPECS_DIR="${CCT_SPECS_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)/specs}"
CONFIG=""
ROUTE_CLASS=""
ROLE=""
FEATURE=""
TASK_ID=""

usage() {
    cat >&2 <<'EOF'
usage: cct routing <command> [options]

  validate [--config automation.json]   validate the registry (and the
           [--feature <id>]             repo restriction block + merge;
                                        with --feature, also the
                                        feature's routing-tasks.yaml
                                        when present — absence is valid
                                        and resolves tier1_only)
  status                                per-profile registry/policy rows
  explain --route-class <class>         pure config-resolution dry run
          [--role <role>] [--config automation.json]

options: --registry <path> (default ~/.code-copilot-team/routing.toml)
EOF
    exit 2
}

CMD="${1:-}"; shift || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --registry)    REGISTRY="$2"; shift 2 ;;
        --config)      CONFIG="$2"; shift 2 ;;
        --route-class) ROUTE_CLASS="$2"; shift 2 ;;
        --role)        ROLE="$2"; shift 2 ;;
        --feature)     FEATURE="$2"; shift 2 ;;
        --task)        TASK_ID="$2"; shift 2 ;;
        *) echo "routing: unknown option '$1'" >&2; usage ;;
    esac
done

require_registry() {
    if [[ ! -r "$REGISTRY" ]]; then
        echo "routing is not configured: no registry at $REGISTRY" >&2
        echo "Copy shared/templates/routing/routing.toml.example there to opt in; absence changes no existing behavior." >&2
        exit 2
    fi
}

# T3 BEFORE composition: with a --config, the standalone automation
# validator must pass before rc_effective ever runs.
checked_effective() {  # -> effective JSON on stdout, or exits 1
    local cfg_arg="-"
    if [[ -n "$CONFIG" ]]; then
        if ! out=$("$SCRIPT_DIR/validate-automation-config.sh" "$CONFIG" 2>&1); then
            echo "$out"
            echo "routing: the automation config fails validation — composition refused (fix the config, then re-run)"
            exit 1
        fi
        cfg_arg="$CONFIG"
    fi
    local eff
    if ! eff=$(rc_effective "$REGISTRY" "$cfg_arg"); then
        printf '%s\n' "$eff"
        exit 1
    fi
    printf '%s' "$eff"
}

state_of() {  # <profile-id> -> state string (unknown when absent)
    if [[ -r "$STATE" ]]; then
        jq -r --arg id "$1" '.profiles[$id].state // "unknown"' "$STATE" 2>/dev/null || echo "unknown"
    else
        echo "unknown"
    fi
}

# Closed CLI surface: --feature belongs to validate, and to explain
# WITH --task (the task-addressed form, #254 T6); --task belongs to
# explain alone and always needs --feature.
if [[ -n "$TASK_ID" && "$CMD" != "explain" ]]; then
    echo "routing: --task is accepted by 'explain' only" >&2
    usage
fi
if [[ -n "$TASK_ID" && -z "$FEATURE" ]]; then
    echo "routing explain: --task requires --feature (the task lives in specs/<feature>/routing-tasks.yaml)" >&2
    usage
fi
if [[ -n "$FEATURE" && "$CMD" != "validate" ]]; then
    if [[ "$CMD" != "explain" || -z "$TASK_ID" ]]; then
        echo "routing: --feature is accepted by 'validate', and by 'explain' together with --task" >&2
        usage
    fi
fi

case "$CMD" in
validate)
    require_registry
    ok=true
    rc_validate "$REGISTRY" || ok=false
    if [[ "$ok" == "true" && -n "$CONFIG" ]]; then
        # checked_effective's exit only leaves the substitution subshell;
        # its diagnostics ride in the captured output and MUST be shown.
        if ! _eff_out=$(checked_effective); then
            printf '%s\n' "$_eff_out"
            exit 1
        fi
    fi
    TASKS_NOTE=""
    if [[ -n "$FEATURE" ]]; then
        RT_ARTIFACT="$SPECS_DIR/$FEATURE/routing-tasks.yaml"
        if [[ -r "$RT_ARTIFACT" ]]; then
            # shellcheck source=/dev/null
            source "$SCRIPT_DIR/lib/routing-tasks.sh"
            RT_VERIF="$SPECS_DIR/$FEATURE/verification.yaml"
            [[ -r "$RT_VERIF" ]] || RT_VERIF="-"
            rk_validate "$RT_ARTIFACT" "$RT_VERIF" "$(dirname "$SPECS_DIR")" || ok=false
            TASKS_NOTE=" (+ task route metadata in $RT_ARTIFACT)"
        else
            TASKS_NOTE=" (no routing-tasks.yaml for '$FEATURE' — every task resolves tier1_only)"
        fi
    fi
    [[ "$ok" == "true" ]] || exit 1
    echo "routing configuration OK: $REGISTRY$( [[ -n "$CONFIG" ]] && printf ' (+ repo restrictions in %s)' "$CONFIG" )$TASKS_NOTE"
    ;;

status)
    require_registry
    if ! rc_validate "$REGISTRY" >/dev/null 2>&1; then
        echo "the registry does not validate — run: cct routing validate" >&2
        exit 1
    fi
    rc_parse "$REGISTRY" || true
    pref=$(rc_get policy preferred_profile 2>/dev/null || echo "")
    en=$(rc_get policy enabled 2>/dev/null || echo "true")
    echo "routing registry: $REGISTRY (enabled: $en)"
    [[ -r "$STATE" ]] || echo "state: none recorded yet — every profile is unknown (increment A never writes state)"
    printf '%-18s %-6s %-8s %-22s %-28s %-10s %s\n' "PROFILE" "TIER" "PRIORITY" "POOL" "TARGET" "STATE" "CREDENTIAL"
    i=0
    while [[ $i -lt $RC_PROFILE_COUNT ]]; do
        ctx="profiles.$i"
        id=$(rc_get "$ctx" id)
        cred="mode"
        if cv=$(rc_get "$ctx" credential_env 2>/dev/null); then
            # PRESENCE only — the value is never read into output.
            # "set" means a NON-EMPTY value is present: ${!cv:-}
            # treats unset and explicitly-empty alike, which is the
            # right equivalence for credential readiness.
            if [[ -n "${!cv:-}" ]]; then cred="env:$cv (set)"; else cred="env:$cv (unset)"; fi
        else
            cred="mode:$(rc_get "$ctx" credential_mode)"
        fi
        mark=""
        [[ "$id" == "$pref" ]] && mark=" *preferred"
        printf '%-18s %-6s %-8s %-22s %-28s %-10s %s%s\n' \
            "$id" "$(rc_get "$ctx" capability_tier)" "$(rc_get "$ctx" priority)" \
            "$(rc_get "$ctx" quota_pool)" \
            "$(rc_get "$ctx" backend)/$(rc_get "$ctx" provider)/$(rc_get "$ctx" model)" \
            "$(state_of "$id")" "$cred" "$mark"
        i=$((i+1))
    done
    ;;

explain)
    require_registry
    if ! rc_validate "$REGISTRY" >/dev/null 2>&1; then
        echo "the registry does not validate — run: cct routing validate" >&2
        exit 1
    fi
    if ! eff=$(checked_effective); then
        printf '%s\n' "$eff"
        exit 1
    fi
    rc_parse "$REGISTRY" || true
    enabled=$(jq -r '.enabled' <<< "$eff")
    allowed_ids=$(jq -r '.candidates[][0]' <<< "$eff")

    if [[ -n "$TASK_ID" ]]; then
        # ── task-addressed explain (#254 T6; closes increment A's
        # recorded deviation). PURE configuration resolution, exactly
        # like the route-class form: the two artifacts are read-only,
        # nothing is probed, selected, executed, or written.
        # shellcheck source=/dev/null
        source "$SCRIPT_DIR/lib/routing-tasks.sh"
        RT_ARTIFACT="$SPECS_DIR/$FEATURE/routing-tasks.yaml"
        if [[ ! -r "$RT_ARTIFACT" ]]; then
            echo "routing explain: no routing-tasks.yaml for feature '$FEATURE' — every task resolves tier1_only; the task-addressed form requires the artifact" >&2
            exit 1
        fi
        RT_VERIF="$SPECS_DIR/$FEATURE/verification.yaml"
        [[ -r "$RT_VERIF" ]] || RT_VERIF="-"
        if ! rk_validate "$RT_ARTIFACT" "$RT_VERIF" "$(dirname "$SPECS_DIR")" >/dev/null 2>&1; then
            echo "routing explain: the task metadata does not validate — run: cct routing validate --feature $FEATURE" >&2
            exit 1
        fi
        rk_parse "$RT_ARTIFACT" >/dev/null 2>&1 || true
        if ! ROUTE_CLASS=$(rk_task_get "$TASK_ID" route_class 2>/dev/null); then
            echo "routing explain: task '$TASK_ID' is not declared in $RT_ARTIFACT (an undeclared task resolves tier1_only; declare it to delegate it)" >&2
            exit 1
        fi
        echo "explain: task '$TASK_ID' (feature '$FEATURE') — route class '$ROUTE_CLASS' from routing-tasks.yaml"
        echo "  this is not an availability decision: nothing is probed, selected, or executed."
        echo "  safety floor evaluation (allowed files):"
        af_any=""
        while IFS= read -r af; do
            [[ -z "$af" ]] && continue
            af_any=1
            hits=$(rk_floor_hits "$af" | tr '\n' ',' | sed 's/,$//')
            if [[ -n "$hits" ]]; then
                echo "    $af: floor category ${hits} — Tier-1 territory"
            else
                echo "    $af: not in the safety floor"
            fi
        done <<< "$(rk_task_items "$TASK_ID" allowed_files)"
        [[ -z "$af_any" ]] && echo "    (no allowed_files declared — a tier1-class task needs none)"
        T2_RESTRICT=0
        if [[ "$ROUTE_CLASS" == tier2_* ]]; then
            if [[ "$(rc_tier2_allowed "$eff")" == "false" ]]; then
                echo "  tier2 delegation: FORBIDDEN by repository policy (routing.tier2.delegation_enabled = false)"
                T2_RESTRICT=1
            else
                echo "  tier2 delegation: permitted by the effective policy"
            fi
        fi
        # the class tier order is CLASS SEMANTICS (closed), not a
        # registry declaration
        case "$ROUTE_CLASS" in
            primary_only|tier1_only) tier_order=$'tier1' ;;
            tier2_fallback)          tier_order=$'tier1\ntier2' ;;
            tier2_preferred)         tier_order=$'tier2\ntier1' ;;
        esac
        [[ "$ROUTE_CLASS" == "primary_only" ]] && \
            echo "  note: 'primary_only' admits only the first tier1 candidate in the total order at selection time"
        echo "  candidates for route class '$ROUTE_CLASS':"
    else
        [[ -n "$ROUTE_CLASS" ]] || { echo "routing explain: --route-class is required" >&2; usage; }
        rc_route_classes | grep -qx "$ROUTE_CLASS" || {
            echo "routing explain: route class '$ROUTE_CLASS' is not declared in the registry" >&2
            exit 1
        }
        echo "explain: CONFIGURATION resolution for route class '$ROUTE_CLASS' —"
        echo "  this is not an availability decision: nothing is probed, selected, or executed."
        tier_order=$(rc_array_elems "route_classes.$ROUTE_CLASS" tier_order)
    fi
    # every profile gets a verdict, in tier order then priority
    while IFS= read -r tier; do
        [[ -z "$tier" ]] && continue
        i=0
        rows=""
        while [[ $i -lt $RC_PROFILE_COUNT ]]; do
            ctx="profiles.$i"
            [[ "$(rc_get "$ctx" capability_tier)" == "$tier" ]] && \
                rows="${rows}$(rc_get "$ctx" priority) $(rc_get "$ctx" id)"$'\n'
            i=$((i+1))
        done
        while read -r _pri id; do
            [[ -z "$id" ]] && continue
            st=$(state_of "$id")
            if [[ "$enabled" != "true" ]]; then
                echo "  $id: rejected — routing is disabled by the effective policy"
            elif [[ "${T2_RESTRICT:-0}" == "1" && "$tier" == "tier2" ]]; then
                # the EFFECTIVE legality --delegate and rt_select
                # enforce — class-level eligibility the policy has
                # removed is never rendered as eligible (#254 T6)
                echo "  $id: excluded by repository policy — tier2 delegation disabled by repository (routing.tier2.delegation_enabled = false)"
            elif ! grep -qx "$id" <<< "$allowed_ids"; then
                echo "  $id: excluded by repository policy (not in the effective allowed set)"
            elif [[ -n "$ROLE" ]] && ! ( rc_array_elems "profiles.$(rc_index_of "$id")" roles | grep -qx "$ROLE" ); then
                echo "  $id: rejected — does not hold role '$ROLE'"
            else
                echo "  $id: eligible in $tier at priority $_pri (state: $st$( [[ "$st" == "unknown" ]] && printf ' — never treated as healthy' ))"
            fi
        done <<< "$(sort -n <<< "$rows")"
    done <<< "$tier_order"
    # profiles whose tier the class never reaches still get a verdict
    i=0
    while [[ $i -lt $RC_PROFILE_COUNT ]]; do
        ctx="profiles.$i"
        t=$(rc_get "$ctx" capability_tier)
        grep -qx "$t" <<< "$tier_order" || \
            echo "  $(rc_get "$ctx" id): rejected — route class '$ROUTE_CLASS' never reaches $t"
        i=$((i+1))
    done
    ;;

*) usage ;;
esac
