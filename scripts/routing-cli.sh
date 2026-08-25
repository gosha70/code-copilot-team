#!/usr/bin/env bash
# routing-cli.sh — `cct routing <validate|status|explain|tick|enable>`
# (#248 A + #257 D).
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
# None of the three pure commands probes a provider, makes a network call, executes
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
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/supervisor-defaults.sh"

REGISTRY="${CCT_ROUTING_REGISTRY:-$HOME/.code-copilot-team/routing.toml}"
STATE="${CCT_ROUTING_STATE:-$HOME/.code-copilot-team/routing-state.json}"
SPECS_DIR="${CCT_SPECS_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)/specs}"
CONFIG=""
TICK_DUE=0
TICK_ONCE=0
TICK_WAKE=0
LEDGER_ROOT="${CCT_SUPERVISOR_DIR:-}"
LEDGER_ROOT_EXPLICIT=0
[[ -n "$LEDGER_ROOT" ]] && LEDGER_ROOT_EXPLICIT=1
ROUTE_CLASS=""
ROLE=""
FEATURE=""
TASK_ID=""
ENABLE_PROFILE=""

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
  tick --due --once [--wake]            IMPURE: globally locked due probes,
                                        probe profiles whose next probe
                                        is due, apply results atomically,
                                        and with --wake relaunch runs
                                        parked for no-eligible-profile
  enable <profile-id>                    IMPURE operator action: move an
                                        auth-disabled profile to probe_due
  explain --route-class <class>         pure config-resolution dry run
          [--role <role>] [--config automation.json]

options: --registry <path> (default ~/.code-copilot-team/routing.toml)
         --ledger-root <path> (wake/failback ledger root; when omitted,
                              discover this repository's git worktrees)
EOF
    exit 2
}

CMD="${1:-}"; shift || true
if [[ "$CMD" == "enable" ]]; then
    ENABLE_PROFILE="${1:-}"
    [[ -n "$ENABLE_PROFILE" ]] || usage
    shift
fi
while [[ $# -gt 0 ]]; do
    case "$1" in
        --registry)    REGISTRY="$2"; shift 2 ;;
        --config)      CONFIG="$2"; shift 2 ;;
        --route-class) ROUTE_CLASS="$2"; shift 2 ;;
        --role)        ROLE="$2"; shift 2 ;;
        --feature)     FEATURE="$2"; shift 2 ;;
        --task)        TASK_ID="$2"; shift 2 ;;
        --due)         TICK_DUE=1; shift ;;
        --once)        TICK_ONCE=1; shift ;;
        --wake)        TICK_WAKE=1; shift ;;
        --ledger-root) LEDGER_ROOT="$2"; LEDGER_ROOT_EXPLICIT=1; shift 2 ;;
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

state_of() {  # <profile-id> <pool> -> EFFECTIVE state string
    if [[ -r "$STATE" ]] && declare -F rs_effective_state >/dev/null 2>&1; then
        rs_effective_state "$1" "$2" 2>/dev/null || echo "unknown"
    else
        echo "unknown"
    fi
}
load_state_reader() {
    [[ -e "$STATE" ]] || return 0
    CCT_ROUTING_STATE="$STATE"
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/lib/routing-state.sh"
    rs_read >/dev/null
}
next_probe_of() { # <profile-id> -> epoch or -
    if [[ -r "$STATE" ]]; then
        jq -r --arg id "$1" '.profiles[$id].next_probe_at // "-"' "$STATE" 2>/dev/null || echo "-"
    else
        echo "-"
    fi
}

# Ledger discovery for scheduled recovery. The supervisor defaults its
# ledger to the RUN'S worktree, while this CLI lives in the installation
# checkout. Treating the installation's .cct directory as the only root
# silently missed every normal `--worktree` run. With no override, scan
# the registered git worktrees for this repository. An explicit root
# (flag or CCT_SUPERVISOR_DIR) remains the operator-owned escape hatch
# for ledgers deliberately stored elsewhere.
routing_ledger_roots() {
    local repo wt root
    if [[ "$LEDGER_ROOT_EXPLICIT" == "1" ]]; then
        printf '%s\n' "$LEDGER_ROOT"
        return 0
    fi
    repo=$(cd "$SCRIPT_DIR/.." && pwd)
    printf '%s\n' "$repo/.cct/supervisor"
    git -C "$repo" worktree list --porcelain 2>/dev/null \
        | sed -n 's/^worktree //p' \
        | while IFS= read -r wt; do
            [[ -n "$wt" ]] && printf '%s\n' "$wt/.cct/supervisor"
          done
}

routing_run_ledgers() {
    local roots root run out=""
    roots=$(routing_ledger_roots | awk '!seen[$0]++')
    while IFS= read -r root; do
        [[ -n "$root" ]] || continue
        for run in "$root"/*/run.json; do
            [[ -e "$run" ]] || continue
            out="${out}${out:+$'\n'}$run"
        done
    done <<< "$roots"
    printf '%s' "$out"
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
enable)
    require_registry
    if ! rc_validate "$REGISTRY" >/dev/null 2>&1; then
        echo "the registry does not validate — run: cct routing validate" >&2
        exit 1
    fi
    rc_parse "$REGISTRY" || true
    rc_index_of "$ENABLE_PROFILE" >/dev/null 2>&1 || {
        echo "routing enable: profile '$ENABLE_PROFILE' is not declared in $REGISTRY" >&2
        exit 1
    }
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/lib/routing-state.sh"
    if ! rs_operator_enable "$ENABLE_PROFILE"; then
        echo "routing enable: '$ENABLE_PROFILE' was not changed" >&2
        exit 1
    fi
    echo "routing enable: $ENABLE_PROFILE is probe_due — the next tick must pass its canary before it can be healthy"
    ;;

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
    # Pure does not mean permissive. A present corrupt store is not
    # equivalent to no evidence; rendering every row as `unknown`
    # would hide exactly the recovery-state damage the operator is
    # asking this command to inspect.
    load_state_reader || exit 1
    pref=$(rc_get policy preferred_profile 2>/dev/null || echo "")
    en=$(rc_get policy enabled 2>/dev/null || echo "true")
    echo "routing registry: $REGISTRY (enabled: $en)"
    [[ -r "$STATE" ]] || echo "state: none recorded yet — every profile is unknown (increment A never writes state)"
    printf '%-18s %-6s %-8s %-22s %-28s %-10s %-12s %s\n' "PROFILE" "TIER" "PRIORITY" "POOL" "TARGET" "STATE" "NEXT_PROBE" "CREDENTIAL"
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
        printf '%-18s %-6s %-8s %-22s %-28s %-10s %-12s %s%s\n' \
            "$id" "$(rc_get "$ctx" capability_tier)" "$(rc_get "$ctx" priority)" \
            "$(rc_get "$ctx" quota_pool)" \
            "$(rc_get "$ctx" backend)/$(rc_get "$ctx" provider)/$(rc_get "$ctx" model)" \
            "$(state_of "$id" "$(rc_get "$ctx" quota_pool)")" "$(next_probe_of "$id")" "$cred" "$mark"
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
    # `explain` renders the same effective state as `status`. Keeping
    # the state library unloaded made state_of's guard return unknown
    # for every profile, hiding the state behind the decision being
    # explained.
    load_state_reader || exit 1
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
            st=$(state_of "$id" "$(rc_get "profiles.$(rc_index_of "$id")" quota_pool)")
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

tick)
    # THE SCHEDULED IMPURE VERB (#257 D T3): validate/status/explain
    # never write; tick probes and applies state. `enable` is the other
    # impure surface, but only as an explicit operator action. Tick is
    # cron/launchd/systemd
    # compatible and IDEMPOTENT — a second immediate run finds nothing
    # due and leaves the state byte-identical.
    require_registry
    [[ "$TICK_DUE" == "1" && "$TICK_ONCE" == "1" ]] || {
        echo "routing tick: --due --once are both required (the portable scheduling contract)" >&2
        usage
    }
    if ! rc_validate "$REGISTRY" >/dev/null 2>&1; then
        echo "the registry does not validate — run: cct routing validate" >&2
        exit 1
    fi
    if ! eff=$(checked_effective); then printf '%s\n' "$eff"; exit 1; fi
    if [[ "$(jq -r '.enabled' <<< "$eff")" != "true" ]]; then
        echo "routing tick: routing is DISABLED by the effective policy — nothing to do" >&2
        exit 0
    fi
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/lib/routing-state.sh"
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/lib/routing-recovery.sh"
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/lib/routing-probe.sh"
    # Journal lines go to STDERR: stdout is the tick's own operator
    # report, and a library journal line must never be captured as a
    # function's return value.
    rs_journal() { echo "routing-tick: $1: $2" >&2; }
    rb_journal() { echo "routing-tick: $1: $2" >&2; }

    # One tick owns the complete probe/apply/wake pass. The short
    # routing-state lock still makes each state publication atomic; this
    # scheduler lock prevents overlapping cron invocations from acting on
    # different snapshots while provider work is outside that write lock.
    if ! rs_tick_trylock; then
        echo "routing tick: another scheduler holds $RS_TICK_LOCK — refusing (a scheduled tick never queues)" >&2
        exit 3
    fi

    # SIGNAL CLEANUP. ca_run_bounded's watchdog only guarantees the
    # bound; reaping on an INTERRUPT is the caller's job, and without
    # it a Ctrl-C or a scheduler TERM leaves real provider work running
    # until the watchdog deadline — up to RB_TIMEOUT_SEC of billed
    # inference nobody is waiting for. The handoff goes through a FILE
    # because the probe runs inside a command substitution, where a
    # variable set by the child is invisible to this shell's handler.
    CA_OWNER_ID="$$"
    CA_ACTIVE_GROUP_FILE=""
    tick_reap() {
        ca_active_cleanup >/dev/null 2>&1 || true
        rs_unlock 2>/dev/null || true
        rs_tick_unlock 2>/dev/null || true
        [[ -n "$CA_ACTIVE_GROUP_FILE" ]] && rm -f "$CA_ACTIVE_GROUP_FILE" 2>/dev/null || true
    }
    trap 'tick_reap; exit 130' INT
    trap 'tick_reap; exit 143' TERM
    trap 'tick_reap; exit 129' HUP
    trap 'tick_reap' EXIT
    CA_ACTIVE_GROUP_FILE=$(mktemp "${TMPDIR:-/tmp}/cct-tick-group.XXXXXX") || {
        echo "routing tick: cannot create the probe handoff record — refusing to run probes that a signal could not reap" >&2
        exit 1
    }
    export CA_OWNER_ID CA_ACTIVE_GROUP_FILE

    # the promoted [policy] threshold (T4 promotes the key itself;
    # the tick reads it with its named default)
    rc_parse "$REGISTRY" || true
    THRESHOLD=$(rc_healthy_probes_required)
    RUN_LEDGER_LIST=$(routing_run_ledgers)

    # CLAIM, don't merely select. Choosing the due profiles and
    # marking them `probing` happen in ONE write under ONE hold of the
    # store lock (rs_claim_due), and the acquisition is non-blocking:
    # a scheduled tick refuses rather than piling up behind another
    # writer. Selecting under the lock and probing after releasing it
    # is the race that lets two ticks probe the SAME due event —
    # two passes, threshold crossed, `healthy` minted out of a single
    # recovery. `probing` is the claim, so a losing tick simply finds
    # nothing due.
    NOW=$(rs_now)
    # `|| CLAIM_RC=$?`, not `; CLAIM_RC=$?`: under errexit a failing
    # command substitution in an assignment kills the shell before the
    # next line runs, and the losing tick would exit MUTE — a refusal
    # nobody can see in a cron log is indistinguishable from a crash.
    CLAIM_RC=0
    CLAIMED=$(rs_claim_due "$NOW") || CLAIM_RC=$?
    if [[ "$CLAIM_RC" -eq 3 ]]; then
        echo "routing tick: another writer holds the routing-state lock — refusing (a scheduled tick never queues)" >&2
        exit 3
    fi
    [[ "$CLAIM_RC" -eq 0 ]] || exit 1

    DUE_PROCESSED=0
    while IFS=$'\t' read -r pid gen prior; do
        [[ -z "$pid" ]] && continue
        idx=$(rc_index_of "$pid" 2>/dev/null || echo "")
        if [[ -z "$idx" ]]; then
            # claimed but unknown to the registry: release the claim to
            # `unknown` on a backoff rather than leaving a marker that
            # every later tick re-claims forever
            sched=$(rd_next_probe_at "$NOW" "$pid" 1 '{}')
            rs_probe_abandon "tick-stale-$pid-$gen" "$pid" "${sched%%$'\t'*}"
            echo "routing tick: claimed profile '$pid' is not in the registry — released to unknown (state is stale)"
            continue
        fi
        # Build from A's canonical executable identity. Reconstructing
        # only the friendly fields here once silently hard-coded
        # endpoint_ref="none", so a due probe tested the default endpoint
        # rather than the profile it claimed to verify.
        tuple=$(rc_profile_tuple "$idx")
        pj=$(jq -nc --argjson c "$tuple" '
            {id:$c[0], backend:$c[1], provider:$c[2], model:$c[3],
             tool_profile:$c[8], credential_ref:$c[10], endpoint_ref:$c[11]}')
        backoff_attempts=$(rs_probe_backoff_count "$pid")

        # an ABANDONED in-flight marker is reconciled and NOT probed:
        # absence of evidence, rescheduled, counters untouched (never
        # probe_fail). The claim decided this — reading the state word
        # again here would re-open the window the claim just closed.
        if [[ "$prior" == "abandoned" ]]; then
            sched=$(rd_next_probe_at "$NOW" "$pid" 1 '{}')
            rs_probe_abandon "tick-abandon-$pid-$gen" "$pid" "${sched%%$'\t'*}"
            echo "routing tick: $pid: abandoned in-flight probe reconciled — unknown, rescheduled (no provider evidence inferred)"
            continue
        fi

        res=$(rb_probe "$pj" "$gen")
        APPLY_NOW=$(rs_now)
        IFS=$'\t' read -r outcome detail pev <<< "$res"
        # the provider's own recovery timing, carried through to the
        # scheduler: a Retry-After outranks any computed backoff
        jq -e 'type == "object"' >/dev/null 2>&1 <<< "$pev" || pev='{}'
        DUE_PROCESSED=$((DUE_PROCESSED + 1))
        case "$outcome" in
            probe_pass)
                rs_probe_pass "tick-pass-$pid-$gen" "$pid" "$THRESHOLD"
                echo "routing tick: $pid: probe_pass — $detail" ;;
            probe_fail)
                sched=$(rd_next_probe_at "$APPLY_NOW" "$pid" $((backoff_attempts + 1)) "$pev")
                rs_probe_fail "tick-fail-$pid-$gen" "$pid" "${sched%%$'\t'*}" "probe failed: $detail"
                echo "routing tick: $pid: probe_fail — $detail; next probe via ${sched#*$'\t'}" ;;
            probe_unverifiable)
                sched=$(rd_next_probe_at "$APPLY_NOW" "$pid" $((backoff_attempts + 1)) "$pev")
                rs_probe_unverifiable "tick-unver-$pid-$gen" "$pid" "${sched%%$'\t'*}" "probe unverifiable: $detail"
                echo "routing tick: $pid: probe_unverifiable — $detail; state stays unknown; next probe via ${sched#*$'\t'}" ;;
            probe_deferred_caps)
                # NOT evidence: restore the schedule marker, never a
                # transition toward health. It still advances the
                # scheduling backoff so a full accounting window does
                # not make every short tick reclaim the same profile.
                sched=$(rd_next_probe_at "$APPLY_NOW" "$pid" $((backoff_attempts + 1)) '{}')
                rs_probe_deferred "tick-defer-$pid-$gen" "$pid" "${sched%%$'\t'*}" "deferred: $detail"
                echo "routing tick: $pid: probe_deferred_caps — $detail; next probe via ${sched#*$'\t'}" ;;
            *)
                # A malformed library result is infrastructure absence,
                # never provider failure and never a marker left in-flight.
                sched=$(rd_next_probe_at "$APPLY_NOW" "$pid" $((backoff_attempts + 1)) '{}')
                rs_probe_unverifiable "tick-invalid-$pid-$gen" "$pid" "${sched%%$'\t'*}" "probe returned unrecognised outcome '$outcome'"
                echo "routing tick: $pid: probe_unverifiable — the probe returned unrecognised outcome '$outcome'; state stays unknown; next probe via ${sched#*$'\t'}" ;;
        esac
    done <<< "$CLAIMED"
    echo "routing tick: $DUE_PROCESSED due profile(s) processed"

    # ── mark active fallback runs for next-boundary failback (FR-D5) ─
    # A run currently executing on something other than the registry's
    # `preferred_profile` is a FALLBACK run. Once the preferred profile
    # is probe-qualified healthy again, the tick marks that run; T4's
    # supervisor consumes the marker at its next TASK BOUNDARY. The
    # tick never switches anything itself — it only records that the
    # evidence now exists.
    # The marker is a SEPARATE file, not a ledger field: the run is
    # live, its supervisor owns run.json, and a concurrent read-modify
    # -write from here would silently drop that supervisor's updates.
    PREFERRED=$(rc_get policy preferred_profile 2>/dev/null || echo "")
    MARKED=0
    if [[ -n "$PREFERRED" ]] && rs_probe_qualified "$PREFERRED" "$THRESHOLD"; then
        PREF_SINCE=$(cut -f2 <<< "$(rs_probe_evidence "$PREFERRED")")
        while IFS= read -r run; do
            [[ -n "$run" && -e "$run" ]] || continue
            jq -e . "$run" >/dev/null 2>&1 || continue
            [[ "$(jq -r '.status' "$run")" == "running" ]] || continue
            # ACTIVE means a supervisor is actually alive on it. This
            # file says elsewhere that `status` cannot establish
            # liveness — a crashed run keeps `running` forever — so the
            # marker would otherwise accumulate on dead ledgers and T4
            # would act on them. The run lock with a LIVE owner is the
            # same proof the wake path uses. T4 revalidates the marker
            # when it consumes it, at the boundary.
            mlock="$(dirname "$run")/routing-run.lock"
            mowner=$(cat "$mlock/pid" 2>/dev/null || echo "")
            [[ -d "$mlock" && "$mowner" =~ ^[0-9]+$ ]] || continue
            kill -0 "$mowner" 2>/dev/null || continue
            active=$(jq -r 'if .routing_profile == null then "" else .routing_profile end' "$run")
            [[ -n "$active" && "$active" != "$PREFERRED" ]] || continue
            mfeat=$(basename "$(dirname "$run")")
            mfile="$(dirname "$run")/failback-marker.json"
            # idempotent: re-marking the same qualification is a no-op
            if [[ -r "$mfile" ]] \
               && [[ "$(jq -r 'if .preferred == null then "" else .preferred end' "$mfile" 2>/dev/null)" == "$PREFERRED" ]] \
               && [[ "$(jq -r 'if .qualified_since == null then "" else (.qualified_since|tostring) end' "$mfile" 2>/dev/null)" == "$PREF_SINCE" ]]; then
                continue
            fi
            mtmp=$(mktemp "$(dirname "$run")/.failback.XXXXXX") || continue
            jq -n --arg p "$PREFERRED" --arg a "$active" --argjson t "$THRESHOLD" \
                  --argjson since "$PREF_SINCE" --argjson now "$NOW" \
                '{schema: 1, preferred: $p, running_on: $a, threshold: $t,
                  qualified_since: $since, marked_at: $now,
                  action: "failback_at_next_task_boundary"}' > "$mtmp" \
              && mv -f "$mtmp" "$mfile" \
              || { rm -f "$mtmp" 2>/dev/null || true; continue; }
            echo "routing tick: $mfeat: running on fallback '$active' while preferred '$PREFERRED' is probe-qualified — marked for failback at the next task boundary"
            jq -nc --arg ev "failback_marked" \
                   --arg detail "running on fallback '$active'; preferred '$PREFERRED' is probe-qualified (>= $THRESHOLD) since $PREF_SINCE — failback at the next task boundary" \
                   --arg t "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
                '{ts: $t, event: $ev, detail: $detail}' >> "$(dirname "$run")/events.jsonl" 2>/dev/null || true
            MARKED=$((MARKED + 1))
        done <<< "$RUN_LEDGER_LIST"
    fi
    echo "routing tick: $MARKED fallback run(s) marked for failback"

    # ── wake (explicit opt-in) ──────────────────────────────────────
    # A wake RECONSTRUCTS a closed supervisor invocation from
    # validated ledger IDENTITY; it never runs a command the ledger
    # supplies. The executable is this installation's own supervisor,
    # every argument comes from a fixed flag list, and every value is
    # re-validated here. The supervisor itself treats run.json as
    # untrusted (fail_corrupt) — a scheduler that took an argument
    # VECTOR from that same file would hand arbitrary execution to
    # anything able to write a ledger.
    if [[ "$TICK_WAKE" == "1" ]]; then
        WOKE=0
        SUPERVISOR="$SCRIPT_DIR/cooldown-supervisor.sh"
        # How long a launched supervisor has to prove it started
        # (tenths of a second). A NAMED implementation default, not
        # configuration — journaled whenever it decides an outcome.
        RW_ACK_TICKS="${RW_ACK_TICKS:-100}"
        if [[ ! -x "$SUPERVISOR" ]]; then
            echo "routing tick: --wake requires $SUPERVISOR from this installation — refusing" >&2
            exit 1
        fi
        while IFS= read -r run; do
            [[ -n "$run" && -e "$run" ]] || continue
            ldir=$(cd "$(dirname "$run")" && pwd -P)
            feat=$(basename "$ldir")
            # Wake outcomes are JOURNALED, not merely printed: a
            # scheduled tick's stdout goes wherever cron sent it, so a
            # claim, a no-op replay or a launch failure would leave no
            # durable record of why a parked run did or did not resume.
            # Closed vocabulary, same {ts,event,detail} shape the
            # supervisor writes, in that run's own events.jsonl.
            wjournal() {  # wjournal <event> <detail>
                case "$1" in
                    wake_claimed|wake_replay_noop|wake_launch_failed|wake_refused|failback_marked) ;;
                    *) set -- "wake_refused" "UNNAMED EVENT '$1' (tick bug): $2" ;;
                esac
                jq -nc --arg ev "$1" --arg detail "$2" \
                       --arg t "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
                    '{ts: $t, event: $ev, detail: $detail}' >> "$ldir/events.jsonl" 2>/dev/null || true
            }
            skip()  { echo "routing tick: $feat: $1"; wjournal wake_refused "$1"; }
            lfail() { echo "routing tick: $feat: wake_launch_failed: $1"; wjournal wake_launch_failed "$1"; }
            jq -e . "$run" >/dev/null 2>&1 || { skip "ledger unreadable — skipping"; continue; }
            [[ "$feat" =~ ^[A-Za-z0-9._-]+$ ]] || { skip "unsafe feature id — refusing"; continue; }

            # 1. the run must CARRY a wake record (routed runs only)
            [[ "$(jq -r '.routing_wake.schema' "$run")" == "1" ]] || continue

            # 2. the REAL disposition an unattended routed run writes.
            # rt_refuse terminates unattended runs as `failed` and
            # attended ones as `parked`; only the unattended pair is
            # auto-wakeable, and an operator decides the other.
            status=$(jq -r '.status' "$run")
            reason=$(jq -r 'if .last_reason == null then "" else .last_reason end' "$run")
            prof=$(jq -r '.profile' "$run")
            [[ "$reason" == routing_no_eligible_profile:* ]] || continue
            if [[ "$prof" != "unattended" ]]; then
                skip "attended run ($prof) — an operator decides (never auto-woken)"; continue
            fi
            if [[ "$status" != "failed" ]]; then
                skip "profile is unattended but status is '$status', not the 'failed' an unattended refusal writes — refusing to act on an inconsistent ledger"; continue
            fi
            [[ "$(jq -r '.routing_wake.profile' "$run")" == "unattended" ]] || {
                skip "the wake record disagrees with .profile — refusing"; continue; }
            wmode=$(jq -r 'if .routing_wake.mode == null then "" else .routing_wake.mode end' "$run")
            case "$wmode" in
                run) ;;
                delegate|reconcile)
                    skip "this is a --$wmode run: its identity is a task plus packet/round state, which a reconstructed ordinary run would not carry — an operator resumes bounded work (never auto-woken)"; continue ;;
                *)  skip "unrecognised wake mode '$wmode' — refusing (the mode discriminator is closed: run|delegate|reconcile)"; continue ;;
            esac
            woi=$(jq -r 'if .routing_wake.on_incomplete == null then "" else .routing_wake.on_incomplete end' "$run")
            case "$woi" in
                park|relaunch) ;;
                *) skip "recorded on-incomplete '$woi' is not park|relaunch — refusing"; continue ;;
            esac
            if [[ "$woi" != "$CCT_SUPERVISOR_DEFAULT_ON_INCOMPLETE" ]]; then
                skip "recorded on-incomplete '$woi' is a non-default operator grant that the mutable ledger cannot authorize for automatic wake — resume it manually"; continue
            fi

            # 3. the worktree must be BOUND to this ledger: the run we
            # found must be the run that worktree's own ledger root
            # holds. Otherwise the recorded path is just a claim.
            wt=$(jq -r 'if .worktree == null then "" else .worktree end' "$run")
            [[ -d "$wt" ]] || { skip "recorded worktree '$wt' is gone — refusing"; continue; }
            wt=$(cd "$wt" && pwd -P)
            wt_top=$(git -C "$wt" rev-parse --show-toplevel 2>/dev/null || echo "")
            [[ -n "$wt_top" ]] && wt_top=$(cd "$wt_top" && pwd -P)
            if [[ "$wt_top" != "$wt" ]]; then
                skip "recorded worktree '$wt' is not the root of a git worktree — refusing an unbound execution directory"; continue
            fi
            bound_ledger="$wt/.cct/supervisor/$feat"
            if [[ "$bound_ledger" != "$ldir" ]]; then
                if [[ "$LEDGER_ROOT_EXPLICIT" != "1" ]]; then
                    skip "recorded worktree '$wt' does not own this ledger ($ldir) — refusing to launch against an unbound worktree"; continue
                fi
                explicit_root=$(cd "$LEDGER_ROOT" 2>/dev/null && pwd -P || echo "")
                if [[ -z "$explicit_root" || "$explicit_root/$feat" != "$ldir" ]]; then
                    skip "ledger '$ldir' is bound neither to the recorded worktree nor to the explicit ledger root '$LEDGER_ROOT' — refusing"; continue
                fi
            fi

            # 4. the closed argument set, each value re-validated
            bk=$(jq -r '.routing_wake.backend' "$run")
            [[ "$bk" == "claude" || "$bk" == "pi" ]] || { skip "recorded backend '$bk' is not claude|pi — refusing"; continue; }
            # 5. THIS repository's policy, resolved from THIS run's
            # worktree — one global effective document cannot speak for
            # several repositories' automation configs. The repository
            # layer is restriction-only: it may veto a wake, never grant
            # one. Validate it through the same executable gate used by
            # --config before composing it; rc_effective is a merge, not
            # a substitute schema validator.
            run_cfg="-"
            candidate_cfg="$wt/specs/$feat/automation.json"
            if [[ -e "$candidate_cfg" ]]; then
                if ! "$SCRIPT_DIR/validate-automation-config.sh" "$candidate_cfg" >/dev/null 2>&1; then
                    skip "this run's automation.json does not validate — refusing to compose wake restrictions"; continue
                fi
                run_cfg="$candidate_cfg"
            fi
            if ! run_eff=$(rc_effective "$REGISTRY" "$run_cfg" 2>&1); then
                skip "the effective policy for this run does not compose — refusing"; continue
            fi
            if [[ "$(jq -r '.enabled' <<< "$run_eff")" != "true" ]]; then
                skip "routing is disabled by this run's effective policy"; continue
            fi
            if [[ "$(rc_wake_allowed "$run_eff")" != "true" ]]; then
                skip "repository policy forbids wake (routing.recovery.wake_enabled = false)"; continue
            fi

            # The backend must be one the USER REGISTRY actually offers
            # for this run — the trusted half of the policy pair. The
            # ledger records the HARNESS backend (claude|pi) while the
            # registry records the profile backend (claude-code|pi|
            # codex), so membership is tested through the supervisor's
            # own frozen mapping rule: `pi` maps to `pi`, everything
            # else maps to `claude`.
            if ! jq -e --arg b "$bk" \
                 '[.candidates[] | (if .[1] == "pi" then "pi" else "claude" end)]
                  | index($b) != null' >/dev/null 2>&1 <<< "$run_eff"; then
                skip "recorded backend '$bk' is offered by no candidate in this run's effective policy — refusing"; continue
            fi

            # 6. Reconstruct only authority owned by this installation.
            # The ledger is evidence, not an operator-owned grant source:
            # matching two fields in that same mutable file cannot prove
            # the original cap grant. Automatic wake therefore serves
            # only the supervisor's code-owned defaults. A non-default
            # run remains manually resumable; inventing a grant here would
            # widen authority merely because a file claimed it.
            if ! WAKE_CAPS=$(jq -ce '
                .routing_wake.caps as $w
                | .caps as $c
                | ($w | type == "object") and ($c | type == "object")
                and (($w | keys | sort) == ["cooldown_sec","max_attempts","max_cooldowns","max_wall_sec"])
                and (($c | keys | sort) == ["cooldown_sec","max_attempts","max_cooldowns","max_wall_sec"])
                and ($w == $c)
                and ([$w.max_attempts,$w.max_cooldowns,$w.cooldown_sec,$w.max_wall_sec]
                     | all(type == "number" and . == floor and . >= 0))
                | select(.)
                | $w' "$run" 2>/dev/null); then
                skip "the recorded structured invocation has missing, malformed, or inconsistent caps — refusing to guess how to resume it"; continue
            fi
            if ! jq -e \
                 --argjson ma "$CCT_SUPERVISOR_DEFAULT_MAX_ATTEMPTS" \
                 --argjson mc "$CCT_SUPERVISOR_DEFAULT_MAX_COOLDOWNS" \
                 --argjson cs "$CCT_SUPERVISOR_DEFAULT_COOLDOWN_SEC" \
                 --argjson mw "$CCT_SUPERVISOR_DEFAULT_MAX_WALL_SEC" \
                 '. == {max_attempts:$ma,max_cooldowns:$mc,
                         cooldown_sec:$cs,max_wall_sec:$mw}' \
                 >/dev/null 2>&1 <<< "$WAKE_CAPS"; then
                skip "the run used non-default caps; their original operator grant cannot be proven from the mutable ledger — resume it manually"; continue
            fi
            CAP_max_attempts="$CCT_SUPERVISOR_DEFAULT_MAX_ATTEMPTS"
            CAP_max_cooldowns="$CCT_SUPERVISOR_DEFAULT_MAX_COOLDOWNS"
            CAP_cooldown_sec="$CCT_SUPERVISOR_DEFAULT_COOLDOWN_SEC"
            CAP_max_wall_sec="$CCT_SUPERVISOR_DEFAULT_MAX_WALL_SEC"

            # 7. something must actually have RECOVERED. A wake is the
            # consequence of recovery, not a retry timer: relaunching
            # while every candidate is still cooling re-parks within
            # seconds, and because each park mints a fresh generation
            # the claim cannot damp it — every tick would wake the
            # same run forever. At least one candidate must be out of
            # cooldown/disabled before we spend a supervisor on it.
            if ! jq -e '.candidates | length > 0' >/dev/null 2>&1 <<< "$run_eff"; then
                skip "no candidate profiles in this run's effective policy"; continue
            fi
            # The predicate is PROBE-QUALIFIED HEALTHY, not "not
            # blocked". `probe_due` after a single pass, `probing`,
            # `unknown` and `degraded` are all outside cooldown while
            # being exactly the states the threshold exists to
            # distinguish — waking on any of them spends a supervisor
            # on evidence that has not met healthy_probes_required.
            # rs_probe_qualified is the same predicate T4's failback
            # uses, so wake and failback can never disagree about what
            # "recovered" means.
            eligible=""
            while IFS=$'\t' read -r cid cpool; do
                [[ -z "$cid" ]] && continue
                # a pool-level block outranks any profile evidence
                case "$(rs_effective_state "$cid" "$cpool")" in
                    pool:cooldown|pool:disabled) continue ;;
                esac
                if rs_probe_qualified "$cid" "$THRESHOLD"; then eligible="$cid"; break; fi
            # A's candidate tuples are POSITIONAL: [0]=id, [6]=quota_pool
            done < <(jq -r '.candidates[] | [.[0], .[6]] | @tsv' <<< "$run_eff")
            if [[ -z "$eligible" ]]; then
                skip "no candidate is probe-qualified healthy (${THRESHOLD} consecutive successes) — a wake now would re-park or run on unverified capacity"; continue
            fi

            # 8. claim the generation under the run lock the SUPERVISOR
            # creates and holds for its whole life. The lock answers
            # "is a supervisor live on this ledger?" — which no ledger
            # field can, since a relaunching supervisor has not written
            # a status yet — and it serializes the read-compare-write
            # of the claim between concurrent ticks.
            rl="$ldir/routing-run.lock"
            if ! mkdir "$rl" 2>/dev/null; then
                rlo=$(cat "$rl/pid" 2>/dev/null || echo "")
                if [[ ! "$rlo" =~ ^[0-9]+$ ]]; then
                    skip "the run lock exists with an unverifiable owner — refusing (inspect $rl)"; continue
                fi
                if kill -0 "$rlo" 2>/dev/null; then
                    skip "a live supervisor (pid $rlo) holds the run lock — refusing the wake"; continue
                fi
                skip "the run lock records dead owner pid $rlo — refusing racy automatic takeover; confirm no supervisor is active, remove $rl, then retry"; continue
            fi
            if ! printf '%s\n' "$$" > "$rl/pid"; then
                rm -rf "$rl" 2>/dev/null || true
                skip "cannot record ownership of the run lock — refusing"; continue
            fi
            release_rl() {
                [[ "$(cat "$rl/pid" 2>/dev/null)" == "$$" ]] || return 1
                rm -rf "$rl" 2>/dev/null || return 1
                [[ ! -e "$rl" ]]
            }

            wgen=$(jq -r 'if .routing_wake.generation == null then "" else (.routing_wake.generation | tostring) end' "$run")
            wclm=$(jq -r 'if .routing_wake.claimed == null then "none" else (.routing_wake.claimed | tostring) end' "$run")
            if [[ ! "$wgen" =~ ^[0-9]+$ ]]; then
                release_rl || true; skip "wake generation '$wgen' is not an integer — refusing"; continue
            fi
            if [[ "$wclm" == "$wgen" ]]; then
                release_rl || true
                echo "routing tick: $feat: wake generation $wgen already claimed — journaled no-op"
                wjournal wake_replay_noop "generation $wgen was already claimed — no launch"
                continue
            fi
            if [[ "$wclm" != "none" ]]; then
                release_rl || true
                skip "wake generation $wgen carries an inconsistent claim for generation '$wclm' — refusing to overwrite another claim"; continue
            fi
            # atomic, SAME-DIRECTORY: a /tmp temp plus mv is a copy
            # across filesystems, not a rename, and loses atomicity
            ctmp=$(mktemp "$ldir/.run.json.XXXXXX") || { release_rl || true; skip "cannot stage the claim — refusing"; continue; }
            if ! jq --argjson g "$wgen" '.routing_wake.claimed = $g' "$run" > "$ctmp" \
                 || ! mv -f "$ctmp" "$run"; then
                rm -f "$ctmp" 2>/dev/null || true
                release_rl || true; skip "could not durably claim wake generation $wgen — refusing to launch unclaimed"; continue
            fi
            # release BEFORE launching: the child acquires this same
            # lock, and the claim (durable) is what keeps a second tick
            # from launching in the gap.
            if ! release_rl; then
                # The child cannot acquire a lock we failed to release.
                # Clear only this generation's unacknowledged claim while
                # the ledger is still otherwise untouched.
                rtmp=$(mktemp "$ldir/.run.json.XXXXXX") || true
                if [[ -n "${rtmp:-}" ]] \
                   && jq --argjson g "$wgen" \
                        'if (.routing_wake.claimed == $g) and (.routing_wake.acked != $g)
                         then .routing_wake.claimed = null else . end' "$run" > "$rtmp" \
                   && mv -f "$rtmp" "$run"; then :; else rm -f "${rtmp:-}" 2>/dev/null || true; fi
                skip "the claimed generation could not release its run lock — nothing launched; inspect $rl"; continue
            fi
            echo "routing tick: $feat: claimed wake generation $wgen; relaunching the recorded run"
            wjournal wake_claimed "generation $wgen claimed; relaunching (mode=$wmode backend=$bk)"

            if [[ -n "${CCT_ROUTING_WAKE_DRYRUN:-}" ]]; then
                printf '%s\n' "$SUPERVISOR" --worktree "$wt" --backend "$bk" \
                    --profile unattended --routing --on-incomplete "$woi" \
                    --max-attempts "$CAP_max_attempts" --max-cooldowns "$CAP_max_cooldowns" \
                    --cooldown-sec "$CAP_cooldown_sec" --max-wall-sec "$CAP_max_wall_sec" \
                    "$feat" > "${CCT_ROUTING_WAKE_DRYRUN}/$feat.argv"
            else
                # Carry the exact authority and destination validated
                # above. A --registry flag is only a shell variable in
                # this process, and an explicit shared --ledger-root is
                # not derivable from the worktree; relying on ambient
                # inheritance makes the child re-resolve both defaults.
                wake_ledger_root=$(dirname "$ldir")
                ( export CCT_ROUTING_REGISTRY="$REGISTRY"
                  export CCT_SUPERVISOR_DIR="$wake_ledger_root"
                  exec "$SUPERVISOR" --worktree "$wt" --backend "$bk" \
                    --profile unattended --routing --on-incomplete "$woi" \
                    --max-attempts "$CAP_max_attempts" --max-cooldowns "$CAP_max_cooldowns" \
                    --cooldown-sec "$CAP_cooldown_sec" --max-wall-sec "$CAP_max_wall_sec" \
                    "$feat" ) >/dev/null 2>&1 &
                WCHILD=$!
                # WAIT FOR A DURABLE ACKNOWLEDGEMENT. The claim is
                # permanent, so consuming it for a launch that never
                # happened would strand the run forever. Liveness
                # POLLING cannot answer this: a fast child acquires and
                # releases the run lock between two polls, and a slow
                # one acquires just after the last poll. The supervisor
                # therefore STAMPS `routing_wake.acked` under the run
                # lock before it does any work, and that durable fact —
                # not a pid sighting — is what we wait for.
                WACK=0; WWAIT=0
                while [[ "$WWAIT" -lt "$RW_ACK_TICKS" ]]; do
                    [[ "$(jq -r 'if .routing_wake.acked == null then "" else (.routing_wake.acked|tostring) end' "$run" 2>/dev/null)" == "$wgen" ]] \
                        && { WACK=1; break; }
                    kill -0 "$WCHILD" 2>/dev/null || break
                    sleep 0.1; WWAIT=$((WWAIT + 1))
                done
                if [[ "$WACK" != "1" ]]; then
                    # Releasing is a COMPARE-AND-SET under the run lock,
                    # never a blind write. Two ways a blind write goes
                    # wrong: the child may acknowledge in the gap
                    # between the last poll and the release (it would
                    # then run with its claim cleared), and a slow
                    # timeout from an OLD generation could clear a
                    # NEWER park's claim. Taking the lock orders us
                    # against the child; testing `claimed == $wgen` and
                    # `acked != $wgen` makes the clear conditional on
                    # the exact state we are undoing.
                    if ! mkdir "$rl" 2>/dev/null; then
                        rlo2=$(cat "$rl/pid" 2>/dev/null || echo "")
                        if [[ "$rlo2" == "$WCHILD" ]]; then
                            echo "routing tick: $feat: the launched supervisor acquired the run lock as the ack window closed — claim generation $wgen stands"
                            wjournal wake_claimed "generation $wgen claimed; supervisor acknowledged late (pid $rlo2)"
                            WOKE=$((WOKE + 1)); continue
                        fi
                        lfail "no acknowledgement, and the run lock is held by pid '$rlo2' — the claim is NOT released (refusing to clear a claim we cannot prove is stale)"; continue
                    fi
                    if ! printf '%s\n' "$$" > "$rl/pid"; then
                        rm -rf "$rl" 2>/dev/null || true
                        lfail "the acknowledgement check could not record run-lock ownership — the claim is left intact"; continue
                    fi
                    RELEASED=0
                    if [[ "$(jq -r 'if .routing_wake.acked == null then "" else (.routing_wake.acked|tostring) end' "$run" 2>/dev/null)" == "$wgen" ]]; then
                        echo "routing tick: $feat: the launched supervisor acknowledged just after the ack window — claim generation $wgen stands"
                        wjournal wake_claimed "generation $wgen claimed; acknowledgement observed after the window"
                        release_rl || lfail "the acknowledged generation could not release the run lock; inspect $rl"
                        WOKE=$((WOKE + 1)); continue
                    fi
                    atmp=$(mktemp "$ldir/.run.json.XXXXXX") || { release_rl || true; lfail "the claim could not be staged for release — inspect $run"; continue; }
                    if jq --argjson g "$wgen" \
                         'if (.routing_wake.claimed == $g) and (.routing_wake.acked != $g)
                          then .routing_wake.claimed = null else . end' "$run" > "$atmp" \
                       && mv -f "$atmp" "$run"; then
                        RELEASED=1
                    else
                        rm -f "$atmp" 2>/dev/null || true
                    fi
                    if ! release_rl; then
                        lfail "the claim update landed but the run lock could not be released — inspect $rl"; continue
                    fi
                    if [[ "$RELEASED" != "1" ]]; then
                        lfail "the claim could not be released — inspect $run"; continue
                    fi
                    lfail "the launched supervisor never acknowledged generation $wgen — claim released, this park stays retryable"
                    continue
                fi
            fi
            WOKE=$((WOKE + 1))
        done <<< "$RUN_LEDGER_LIST"
        echo "routing tick: $WOKE run(s) woken"
    fi
    ;;

*) usage ;;
esac
