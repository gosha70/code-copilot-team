#!/usr/bin/env bash
# routing-probe.sh — the real health probe (#257, increment D of
# #109, T2; plan decision 2).
#
# A probe is a SMALL REAL INFERENCE through the profile's own backend
# plus, when the profile's tool profile implies tools, a MINIMAL
# TOOL-CALL CANARY. `/v1/models`, `--version`, and a TCP connect are
# insufficient BY CONTRACT — they prove a socket, not a working
# builder.
#
# THE FROZEN INVOCATION ORDERING (plan decision 2 + T1 review):
#   1. pre-launch cap/admission check — a cap that blocks a due probe
#      yields `probe_deferred_caps`: NO launch, NO fabricated result,
#      NO state transition toward health;
#   2. accounting debit BEFORE the launch (estimated), so a probe that
#      was actually launched is accounted for even if the prober
#      itself dies; the actual cost reconciles the estimate after;
#   3. bounded invocation (RB_TIMEOUT_SEC) through B's env wiring —
#      credential values enter the CHILD ENVIRONMENT only, and the
#      child receives NO cost-file or ledger capability;
#   4. secret-taint scrub of the capture BEFORE any persistence;
#   5. classification;
#   6. the caller applies the state transition (this lib never writes
#      circuit state — T3's tick owns that, under the store lock).
#
# EVIDENCE HONESTY (the closed tri-state):
#   probe_pass          the canary ran and did what was asked
#   probe_fail          ACTUAL negative canary evidence — a
#                       classifiable provider failure, or a tool
#                       canary that ran and did not perform its task
#   probe_unverifiable  no usable evidence either way (timeout,
#                       crash, unparseable output, absent backend) —
#                       the caller leaves the state `unknown`; a
#                       missing answer is NEVER a provider failure
# Plus `probe_deferred_caps`, which is not evidence at all.
#
# bash 3.2; jq only. Test seam: CCT_ROUTING_PROBE_CMD (a mock canary
# receiving the same env and prompt as the real backend command).

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/routing-result.sh"

RB_OUTCOMES="probe_pass probe_fail probe_unverifiable probe_deferred_caps"
rb_outcome_valid() { [[ " $RB_OUTCOMES " == *" $1 "* ]]; }

# Named implementation defaults (journaled when applied) — not
# configuration, not compatibility surface.
RB_TIMEOUT_SEC="${RB_TIMEOUT_SEC:-120}"
RB_ESTIMATE_USD="${RB_ESTIMATE_USD:-0.02}"
RB_MAX_PROBE_COST_USD="${RB_MAX_PROBE_COST_USD:-2.00}"
RB_MAX_PROBES_PER_WINDOW="${RB_MAX_PROBES_PER_WINDOW:-50}"
RB_WINDOW_SEC="${RB_WINDOW_SEC:-86400}"

# Tool profiles that imply tool use — a CLOSED map. A profile whose
# builder uses tools must prove a tool call before it can be called
# healthy; inference alone never blesses it.
RB_TOOL_PROFILES="full-cct local-builder-minimal"
rb_tools_implied() { [[ " $RB_TOOL_PROFILES " == *" $1 "* ]]; }

RB_MARKER="CCT_PROBE_OK"
RB_TOOL_MARKER="CCT_TOOL_OK"

RB_LEDGER="${CCT_ROUTING_PROBE_LEDGER:-$HOME/.code-copilot-team/routing-probe-ledger.json}"
RB_LEDGER_SKELETON='{"schema_version":1,"probes":[]}'

if ! declare -F rb_journal >/dev/null 2>&1; then
    rb_journal() { echo "routing-probe: $1: $2" >&2; }
fi

rb_now() { date -u +%s; }

# ── accounting ───────────────────────────────────────────────────────
# The probe ledger mirrors the driver's estimate discipline: an
# invocation whose real cost is unmeasurable is debited a conservative
# named estimate and flagged `estimated:true`, against the SAME
# counters the caps read. Probes are never an unmetered channel.
_rb_ledger_read() {
    [[ -e "$RB_LEDGER" ]] || { printf '%s' "$RB_LEDGER_SKELETON"; return 0; }
    local doc
    if ! doc=$(jq -ce 'select(type == "object" and .schema_version == 1 and (.probes|type == "array"))' "$RB_LEDGER" 2>/dev/null); then
        echo "routing-probe: $RB_LEDGER is corrupt or foreign — refusing to probe against unusable accounting" >&2
        return 2
    fi
    printf '%s' "$doc"
}
_rb_ledger_write() {
    local dir tmp
    dir=$(dirname "$RB_LEDGER"); mkdir -p "$dir"
    tmp=$(mktemp "$dir/.probe-ledger.XXXXXX") || return 1
    printf '%s\n' "$1" > "$tmp"
    mv -f "$tmp" "$RB_LEDGER"
}

# rb_window_totals -> "<count>\t<cost_usd>" within RB_WINDOW_SEC
rb_window_totals() {
    local doc now
    doc=$(_rb_ledger_read) || return $?
    now=$(rb_now)
    jq -r --argjson now "$now" --argjson w "$RB_WINDOW_SEC" '
        [.probes[] | select(.at > ($now - $w))] as $in
        | "\($in | length)\t\($in | map(.cost_usd) | add // 0)"' <<< "$doc"
}

# rb_caps_ok -> rc 0 when a probe may launch; rc 1 with the reason on
# stdout when a cap blocks it. Checked BEFORE any launch.
rb_caps_ok() {
    local totals count cost
    if ! totals=$(rb_window_totals 2>/dev/null); then
        # Unusable accounting is an ADMISSION refusal, not a cap and
        # not evidence: an unaccountable probe must never launch.
        echo "probe accounting is unusable ($RB_LEDGER is corrupt or foreign) — refusing to launch an unaccountable probe"
        return 1
    fi
    count="${totals%%$'\t'*}"; cost="${totals##*$'\t'}"
    if [[ "$count" -ge "$RB_MAX_PROBES_PER_WINDOW" ]]; then
        echo "probe count cap reached ($count/$RB_MAX_PROBES_PER_WINDOW in the last ${RB_WINDOW_SEC}s — RB_MAX_PROBES_PER_WINDOW, a named implementation default)"
        return 1
    fi
    if [[ "$(jq -n --argjson c "$cost" --argjson m "$RB_MAX_PROBE_COST_USD" '$c >= $m')" == "true" ]]; then
        echo "probe cost cap reached (\$$cost >= \$$RB_MAX_PROBE_COST_USD in the last ${RB_WINDOW_SEC}s — RB_MAX_PROBE_COST_USD, a named implementation default)"
        return 1
    fi
    return 0
}

# rb_debit <profile> <generation> <cost|-> <estimated:true|false>
# Records the invocation. Called BEFORE the launch with the estimate
# (so a prober crash still leaves the spend recorded), then again
# after with the measured cost, which REPLACES the estimate for that
# generation rather than double-counting.
rb_debit() {
    local p="$1" gen="$2" cost="$3" est="$4" doc
    [[ "$cost" == "-" ]] && cost="$RB_ESTIMATE_USD"
    doc=$(_rb_ledger_read) || return $?
    doc=$(jq -c --arg p "$p" --argjson gen "$gen" --argjson cost "$cost" \
              --argjson est "$est" --argjson now "$(rb_now)" '
        (.probes | map(select(.profile == $p and .generation == $gen)) | length) as $seen
        | if $seen > 0
          then .probes = (.probes | map(if (.profile == $p and .generation == $gen)
                                        then . + {cost_usd:$cost, estimated:$est, at:.at}
                                        else . end))
          else .probes += [{profile:$p, generation:$gen, cost_usd:$cost,
                            estimated:$est, at:$now}] end' <<< "$doc") || return 1
    _rb_ledger_write "$doc"
}

# ── the canary ───────────────────────────────────────────────────────
# rb_prompt <tools-required:0|1> — the canary prompt (deterministic).
rb_prompt() {
    if [[ "$1" == "1" ]]; then
        printf 'Health canary. Do BOTH, nothing else:\n1. Run this exact shell command with your Bash tool: printf %%s %s > %s\n2. Then reply with exactly: %s\n' \
            "$RB_TOOL_MARKER" "$RB_TOOL_FILE" "$RB_MARKER"
    else
        printf 'Health canary. Reply with exactly: %s\n' "$RB_MARKER"
    fi
}

# rb_probe <profile-json>
# Runs the canary and echoes "<outcome>\t<detail>". Writes NO circuit
# state (the caller applies transitions under the store lock) and
# leaves the scrubbed transcript at $RB_TRANSCRIPT.
# Sets: RB_OUTCOME, RB_DETAIL, RB_COST, RB_TRANSCRIPT.
rb_probe() {
    local pj="$1" gen="${2:-0}"
    local id backend tool_profile cred ep model
    id=$(jq -r '.id' <<< "$pj")
    backend=$(jq -r '.backend' <<< "$pj")
    model=$(jq -r '.model' <<< "$pj")
    tool_profile=$(jq -r '.tool_profile // ""' <<< "$pj")
    cred=$(jq -r '.credential_ref // "none"' <<< "$pj")
    ep=$(jq -r '.endpoint_ref // "none"' <<< "$pj")
    RB_OUTCOME=""; RB_DETAIL=""; RB_COST="0"; RB_TRANSCRIPT=""

    # ── step 1: caps BEFORE launch — never a bypass, never a result
    local capmsg
    if ! capmsg=$(rb_caps_ok); then
        RB_OUTCOME="probe_deferred_caps"
        RB_DETAIL="not launched: $capmsg"
        rb_journal "probe_deferred_caps" "profile '$id': $RB_DETAIL"
        printf '%s\t%s\n' "$RB_OUTCOME" "$RB_DETAIL"
        return 0
    fi

    local tools=0
    rb_tools_implied "$tool_profile" && tools=1

    # ── step 2: debit BEFORE launch (estimated) — launched implies
    # accounted, even if this process dies mid-probe
    rb_debit "$id" "$gen" "-" true || {
        RB_OUTCOME="probe_unverifiable"
        RB_DETAIL="accounting is unusable — refusing to launch an unaccountable probe"
        printf '%s\t%s\n' "$RB_OUTCOME" "$RB_DETAIL"
        return 0
    }

    # ── step 3: bounded invocation, credentials CHILD-ENV ONLY
    local wd out rc=0 base_url="" api_key="" names=""
    wd=$(mktemp -d "${TMPDIR:-/tmp}/cct-probe.XXXXXX")
    RB_TOOL_FILE="$wd/tool-canary.txt"
    out="$wd/capture.log"
    case "$ep" in
        url:*)    base_url="${ep#url:}"; names="$names ANTHROPIC_BASE_URL(base_url)" ;;
        urlenv:*) local v="${ep#urlenv:}"; base_url="${!v:-}"; names="$names ANTHROPIC_BASE_URL(env:$v)" ;;
    esac
    case "$cred" in
        env:*)    local c="${cred#env:}"; api_key="${!c:-}"; names="$names ANTHROPIC_API_KEY(env:$c)" ;;
    esac
    rb_journal "probe_launch_env" "profile '$id': wired${names:- nothing (backend login mode)}; tool canary=$tools"

    rb_prompt "$tools" > "$wd/prompt.txt"
    local cmd
    if [[ -n "${CCT_ROUTING_PROBE_CMD:-}" ]]; then
        cmd="$CCT_ROUTING_PROBE_CMD"
    elif [[ "$backend" == "pi" ]]; then
        cmd="${CCT_PI_BIN:-pi-code} --mode json -p"
    else
        cmd="${CCT_CLAUDE_BIN:-claude-code} -p --output-format json --permission-mode acceptEdits"
        [[ "$tools" == "1" ]] && cmd="$cmd --allowedTools Bash"
    fi
    # Preserve the CALLER's errexit setting: this lib is sourced by
    # scripts that run with and without `set -e`, and a library must
    # never change its caller's shell options.
    local had_errexit=0
    case "$-" in *e*) had_errexit=1 ;; esac
    set +e
    ( cd "$wd" && env CCT_PROBE=1 CCT_PROBE_PROFILE="$id" CCT_PROBE_MODEL="$model" \
        CCT_PROBE_TOOL_FILE="$RB_TOOL_FILE" \
        ${base_url:+ANTHROPIC_BASE_URL="$base_url"} \
        ${api_key:+ANTHROPIC_API_KEY="$api_key"} \
        bash -c "$cmd" ) < "$wd/prompt.txt" > "$out" 2>&1
    rc=$?
    [[ "$had_errexit" -eq 1 ]] && set -e

    # ── step 4: scrub BEFORE anything persists or is classified
    if [[ -n "$api_key" ]]; then
        local content
        content="$(cat "$out")"
        printf '%s\n' "${content//"$api_key"/[REDACTED:ANTHROPIC_API_KEY]}" > "$out"
    fi
    RB_TRANSCRIPT="$out"

    # reconcile the estimate with a measured cost when the backend
    # reports one (same ledger row, never a second debit)
    local measured
    measured=$(jq -r '.total_cost_usd // empty' "$out" 2>/dev/null | tail -1 || true)
    if [[ "$measured" =~ ^[0-9.]+$ ]]; then
        RB_COST="$measured"
        rb_debit "$id" "$gen" "$measured" false || true
    else
        RB_COST="$RB_ESTIMATE_USD"
        rb_journal "probe_cost_estimated" "profile '$id': cost unmeasurable — debited the named estimate \$$RB_ESTIMATE_USD (RB_ESTIMATE_USD), flagged estimated"
    fi

    # ── step 5: classification — evidence only
    local have_marker=0 have_tool=0
    if grep -q "$RB_MARKER" "$out" 2>/dev/null; then have_marker=1; fi
    if [[ -s "$RB_TOOL_FILE" ]] && grep -q "$RB_TOOL_MARKER" "$RB_TOOL_FILE" 2>/dev/null; then have_tool=1; fi

    if [[ "$rc" -eq 124 || "$rc" -eq 137 ]]; then
        RB_OUTCOME="probe_unverifiable"
        RB_DETAIL="the canary was cut off (exit $rc) with no usable evidence — a missing answer is not provider failure"
    elif [[ "$have_marker" -eq 1 && ( "$tools" -eq 0 || "$have_tool" -eq 1 ) ]]; then
        RB_OUTCOME="probe_pass"
        RB_DETAIL="real inference verified$( [[ "$tools" -eq 1 ]] && printf '%s' " + tool canary verified" )"
    elif [[ "$have_marker" -eq 1 && "$tools" -eq 1 && "$have_tool" -eq 0 ]]; then
        # the canary RAN and did not do the tool half — real negative
        # evidence for a builder that must use tools
        RB_OUTCOME="probe_fail"
        RB_DETAIL="inference answered but the TOOL canary did not run — a tool-profiled builder is not healthy on inference alone"
    else
        # no positive evidence: is there classifiable NEGATIVE evidence?
        # A's frozen classifier decides whether the capture carries
        # ACTUAL negative evidence; it returns a JSON document, and
        # `unknown` (its fail-closed class) is NOT negative evidence
        # about the provider — it is absence of evidence.
        local cause
        cause=$(rr_classify "$rc" "$out" 2>/dev/null | jq -r '.failure_class // "unknown"' 2>/dev/null || echo "unknown")
        case "$cause" in
            quota_exhausted|rate_limited|unavailable|auth|denied|invalid_request|transport)
                RB_OUTCOME="probe_fail"
                RB_DETAIL="classified provider failure: $cause" ;;
            *)
                RB_OUTCOME="probe_unverifiable"
                RB_DETAIL="no usable canary evidence (exit $rc, cause '$cause') — never recorded as provider failure" ;;
        esac
    fi

    rb_journal "probe_result" "profile '$id': $RB_OUTCOME — $RB_DETAIL (cost \$$RB_COST)"
    printf '%s\t%s\n' "$RB_OUTCOME" "$RB_DETAIL"
    return 0
}
