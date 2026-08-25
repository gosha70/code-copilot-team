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
# The bounded runner is shared, not reimplemented: a second hand-rolled
# watchdog is a second thing that can silently fail to enforce.
if ! declare -F ca_run_bounded >/dev/null 2>&1; then
    # shellcheck source=/dev/null
    source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/conformance-app.sh"
fi
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

# rb_reserve <profile> <generation> -> rc 0 when the probe may launch
# and its estimated spend is RESERVED; rc 1 with the reason on stdout
# when a cap blocks it; rc 2 when accounting itself is unavailable.
#
# ONE LOCKED TRANSACTION. Checking caps and then reserving separately
# is a check-then-act race: probes run concurrently by design (T3
# releases the state lock before probing), so N of them read the same
# pre-reservation totals, all decide there is room, and all launch —
# a count cap of 1 admitted 20. The cap must be evaluated against the
# same document the reservation is written into, under the same hold.
rb_reserve() {
    local p="$1" gen="$2" doc totals count cost msg rc=0
    _rb_lock || { echo "probe accounting lock unavailable — refusing to launch an unaccountable probe"; return 2; }
    if ! doc=$(_rb_ledger_read 2>/dev/null); then
        _rb_unlock || true
        echo "probe accounting is unusable ($RB_LEDGER is corrupt or foreign) — refusing to launch an unaccountable probe"
        return 2
    fi
    local now; now=$(rb_now)
    totals=$(jq -r --argjson now "$now" --argjson w "$RB_WINDOW_SEC" '
        [.probes[] | select(.at > ($now - $w))] as $in
        | "\($in | length)\t\($in | map(.cost_usd) | add // 0)"' <<< "$doc")
    count="${totals%%$'\t'*}"; cost="${totals##*$'\t'}"
    if [[ "$count" -ge "$RB_MAX_PROBES_PER_WINDOW" ]]; then
        msg="probe count cap reached ($count/$RB_MAX_PROBES_PER_WINDOW in the last ${RB_WINDOW_SEC}s — RB_MAX_PROBES_PER_WINDOW, a named implementation default)"
        rc=1
    elif [[ "$(jq -n --argjson c "$cost" --argjson e "$RB_ESTIMATE_USD" --argjson m "$RB_MAX_PROBE_COST_USD" '$c + $e > $m')" == "true" ]]; then
        msg="probe cost cap reached (\$$cost + \$$RB_ESTIMATE_USD estimated reservation would exceed \$$RB_MAX_PROBE_COST_USD in the last ${RB_WINDOW_SEC}s — RB_MAX_PROBE_COST_USD, a named implementation default)"
        rc=1
    fi
    if [[ "$rc" -ne 0 ]]; then
        if ! _rb_unlock; then
            echo "probe accounting lock could not be released after a cap decision"
            return 2
        fi
        echo "$msg"
        return 1
    fi
    doc=$(jq -c --arg p "$p" --argjson gen "$gen" --argjson cost "$RB_ESTIMATE_USD" \
              --argjson now "$now" '
        .probes += [{profile:$p, generation:$gen, cost_usd:$cost,
                     estimated:true, at:$now}]' <<< "$doc") || { _rb_unlock || true; echo "could not stage the probe reservation"; return 2; }
    _rb_ledger_write "$doc" || { _rb_unlock || true; echo "could not write the probe reservation"; return 2; }
    if ! _rb_unlock; then
        echo "probe accounting reservation was written but its lock could not be released"
        return 2
    fi
    return 0
}

# rb_debit <profile> <generation> <cost|-> <estimated:true|false>
# Records the invocation. Called BEFORE the launch with the estimate
# (so a prober crash still leaves the spend recorded), then again
# after with the measured cost, which REPLACES the estimate for that
# generation rather than double-counting.
# The read-modify-write is SERIALISED. Atomic rename keeps the file
# from ever being torn, but it does not stop a lost update: T3 releases
# the routing-state lock before probing (so probes run concurrently by
# design), and two overlapping debits that both read the same document
# would publish one and silently discard the other. A dropped row means
# a launched probe went unaccounted — breaking both "launched implies
# accounted" and every cap that counts rows.
_rb_lock() {
    local dir="${RB_LEDGER}.lock" waited=0
    mkdir -p "$(dirname "$RB_LEDGER")" 2>/dev/null || true
    while ! mkdir "$dir" 2>/dev/null; do
        # Do not reclaim by PID check. The observed owner can release
        # and a replacement can acquire before deletion, causing this
        # process to remove a live writer's lock. Accounting refuses
        # until the existing lock is cleared by its owner or operator.
        sleep 1
        waited=$((waited + 1))
        if [[ "$waited" -ge "${RB_LOCK_WAIT_SEC:-30}" ]]; then
            echo "routing-probe: could not acquire the accounting lock $dir — refusing to debit unserialised" >&2
            return 1
        fi
    done
    if ! printf '%s\n' "$$" > "${dir}/pid"; then
        rm -rf "$dir" 2>/dev/null || true
        return 1
    fi
}
_rb_unlock() {
    local dir="${RB_LEDGER}.lock"
    if [[ "$(cat "$dir/pid" 2>/dev/null)" != "$$" ]]; then
        echo "routing-probe: cannot release accounting lock $dir because ownership is no longer provable" >&2
        return 1
    fi
    rm -rf "$dir" 2>/dev/null || return 1
}

rb_debit() {
    local p="$1" gen="$2" cost="$3" est="$4" doc rc=0
    [[ "$cost" == "-" ]] && cost="$RB_ESTIMATE_USD"
    _rb_lock || return 1
    doc=$(_rb_ledger_read) || { rc=$?; _rb_unlock; return $rc; }
    doc=$(jq -c --arg p "$p" --argjson gen "$gen" --argjson cost "$cost" \
              --argjson est "$est" --argjson now "$(rb_now)" '
        (.probes | map(select(.profile == $p and .generation == $gen)) | length) as $seen
        | if $seen > 0
          then .probes = (.probes | map(if (.profile == $p and .generation == $gen)
                                        then . + {cost_usd:$cost, estimated:$est, at:.at}
                                        else . end))
          else .probes += [{profile:$p, generation:$gen, cost_usd:$cost,
                            estimated:$est, at:$now}] end' <<< "$doc") || { _rb_unlock; return 1; }
    _rb_ledger_write "$doc" || { _rb_unlock || true; return 1; }
    _rb_unlock || return 1
}

# ── the canary ───────────────────────────────────────────────────────
# rb_prompt <tools-required:0|1> — the canary prompt (deterministic).
rb_prompt() {
    local tools="$1" expected="$2"
    if [[ "$tools" == "1" ]]; then
        printf 'Health canary. Do BOTH, nothing else:\n1. Run this exact shell command with your Bash tool: printf %%s %s > %s\n2. Then reply with exactly this single line: %s\n' \
            "$RB_TOOL_MARKER" "$RB_TOOL_FILE" "$expected"
    else
        printf 'Health canary. Reply with exactly this single line: %s\n' "$expected"
    fi
}

# Read the backend's JSON/JSONL records without letting one diagnostic
# line invalidate every structured record around it. First accept a
# wholly valid JSON stream (including pretty-printed JSON); otherwise
# fall back to independently parsing complete JSON lines and ignore
# non-JSON notices. Consumers still apply their own closed shapes.
rb_json_records() {
    local records
    if records=$(jq -c . "$1" 2>/dev/null); then
        printf '%s\n' "$records"
    else
        jq -Rc 'fromjson?' "$1" 2>/dev/null || true
    fi
}

# Parse only a backend-authored response field. The prompt itself also
# appears in several CLI transcript shapes; grepping the merged stream
# lets a backend that merely echoes its input manufacture health. The
# accepted shapes mirror the repo's headless-session contract: a result
# object's `result`, or the last assistant text message. A raw line or a
# user/prompt event is never positive evidence.
rb_result_text() {
    rb_json_records "$1" | jq -r -s '
      map(if type == "array" then .[] else . end) as $docs
      | ([ $docs[] | select(type == "object" and .type? == "result"
                            and ((.result? | type) == "string"))
           | .result ] | last)
        // ([ $docs[] | select(type == "object" and .type? == "assistant")
              | if ((.message?.content? | type) == "array") then
                  [ .message.content[]
                    | select(type == "object" and .type? == "text"
                             and ((.text? | type) == "string"))
                    | .text ] | join("")
                elif ((.message? | type) == "string") then .message
                elif ((.content? | type) == "string") then .content
                else empty end ] | last)
        // (if ($docs | length) == 1
               and (($docs[0] | type) == "object")
               and (($docs[0].result? | type) == "string")
            then $docs[0].result else empty end)
        // empty
      | gsub("^\\s+|\\s+$"; "")' 2>/dev/null || true
}

# Measured cost uses the same closed stream normalization as reviewer
# accounting. A malformed numeric-looking string (for example `1.2.3`)
# is unmetered and keeps the conservative reservation; it must not turn
# an otherwise valid canary into an infrastructure failure.
rb_measured_cost() {
    rb_json_records "$1" | jq -r -s '
      map(if type == "array" then .[] else . end) as $docs
      | ([ $docs[] | select(type == "object" and .type? == "result") ] | last)
        // (if ($docs | length) == 1
               and (($docs[0] | type) == "object")
               and (($docs[0] | has("type")) | not)
            then $docs[0] else {} end)
      | if ((.total_cost_usd? | type) == "number")
           and .total_cost_usd >= 0
        then .total_cost_usd else empty end' 2>/dev/null || true
}

rb_probe_cleanup() {
    local wd="$1"
    rm -rf "$wd" 2>/dev/null || true
    RB_TRANSCRIPT=""
}

# rb_probe <profile-json> [generation]
# Runs the canary and echoes "<outcome>\t<detail>\t<evidence-json>".
# The third field is the provider's own RECOVERY TIMING, normalized
# out of the same capture the outcome was classified from
# ({reset_at, retry_after_sec, rate_limits_resets_at}, each explicitly
# null when the provider said nothing) — it is what the caller feeds
# to rd_next_probe_at so a provider-supplied instant outranks a
# computed backoff. `{}` whenever no capture was classified (deferred
# caps, unusable accounting).
# Writes NO circuit state (the caller applies transitions under the
# store lock). The scrubbed transcript exists only for classification;
# the private probe directory is removed on every return path.
# Sets: RB_OUTCOME, RB_DETAIL, RB_COST, RB_TRANSCRIPT, RB_EVIDENCE.
rb_probe() {
    local pj="$1" gen="${2:-0}"
    local id backend tool_profile cred ep model
    id=$(jq -r '.id' <<< "$pj")
    backend=$(jq -r '.backend' <<< "$pj")
    model=$(jq -r '.model' <<< "$pj")
    tool_profile=$(jq -r '.tool_profile // ""' <<< "$pj")
    cred=$(jq -r '.credential_ref // "none"' <<< "$pj")
    ep=$(jq -r '.endpoint_ref // "none"' <<< "$pj")
    RB_OUTCOME=""; RB_DETAIL=""; RB_COST="0"; RB_TRANSCRIPT=""; RB_EVIDENCE="{}"

    # ── step 0: the EXECUTION MECHANISM before any spend. A bound we
    # cannot enforce means the probe will not run, so reserving for it
    # first would debit a launch that never happens.
    if [[ ! "$RB_TIMEOUT_SEC" =~ ^[0-9]+$ ]] || [[ "$RB_TIMEOUT_SEC" -lt 1 ]]; then
        RB_OUTCOME="probe_unverifiable"
        RB_DETAIL="RB_TIMEOUT_SEC='$RB_TIMEOUT_SEC' is not a positive integer — refusing to run an unbounded probe"
        rb_journal "probe_unverifiable" "profile '$id': $RB_DETAIL"
        printf '%s\t%s\t%s\n' "$RB_OUTCOME" "$RB_DETAIL" "$RB_EVIDENCE"
        return 0
    fi

    local tools=0
    rb_tools_implied "$tool_profile" && tools=1

    # Establish the private execution root BEFORE reserving spend. A
    # failed sandbox setup is not a provider invocation and must neither
    # debit the probe budget nor fall through to execution in the caller's
    # directory.
    local wd stdout_file stderr_file capture child_private rc=0 base_url="" api_key="" names=""
    if ! wd=$(mktemp -d "${TMPDIR:-/tmp}/cct-probe.XXXXXX"); then
        RB_OUTCOME="probe_unverifiable"
        RB_DETAIL="the probe sandbox could not be created — refusing to execute provider code outside the isolated probe directory"
        rb_journal "probe_unverifiable" "profile '$id': $RB_DETAIL"
        printf '%s\t%s\t%s\n' "$RB_OUTCOME" "$RB_DETAIL" "$RB_EVIDENCE"
        return 0
    fi
    RB_TOOL_FILE="$wd/tool-canary.txt"
    stdout_file="$wd/stdout.log"
    stderr_file="$wd/stderr.log"
    capture="$wd/capture.log"
    child_private="$wd/untrusted-routing"
    if ! mkdir -p "$child_private"; then
        rb_probe_cleanup "$wd"
        RB_OUTCOME="probe_unverifiable"
        RB_DETAIL="the private child routing paths could not be created — refusing to expose active routing state"
        rb_journal "probe_unverifiable" "profile '$id': $RB_DETAIL"
        printf '%s\t%s\t%s\n' "$RB_OUTCOME" "$RB_DETAIL" "$RB_EVIDENCE"
        return 0
    fi

    # ── step 1+2: caps AND the estimated reservation, atomically.
    # These were two steps and raced: N concurrent probes read the same
    # pre-reservation totals and all admitted themselves past a cap of
    # one. Admission and reservation are now one locked transaction —
    # and it still happens BEFORE the launch, so a probe that ran is
    # accounted even if this process dies mid-probe.
    local capmsg caprc=0
    capmsg=$(rb_reserve "$id" "$gen") || caprc=$?
    if [[ "$caprc" -eq 1 ]]; then
        rb_probe_cleanup "$wd"
        RB_OUTCOME="probe_deferred_caps"
        RB_DETAIL="not launched: $capmsg"
        rb_journal "probe_deferred_caps" "profile '$id': $RB_DETAIL"
        printf '%s\t%s\t%s\n' "$RB_OUTCOME" "$RB_DETAIL" "$RB_EVIDENCE"
        return 0
    elif [[ "$caprc" -ne 0 ]]; then
        rb_probe_cleanup "$wd"
        RB_OUTCOME="probe_unverifiable"
        RB_DETAIL="not launched: $capmsg"
        rb_journal "probe_unverifiable" "profile '$id': $RB_DETAIL"
        printf '%s\t%s\t%s\n' "$RB_OUTCOME" "$RB_DETAIL" "$RB_EVIDENCE"
        return 0
    fi

    # ── step 3: bounded invocation, credentials CHILD-ENV ONLY
    case "$ep" in
        url:*)    base_url="${ep#url:}"; names="$names ANTHROPIC_BASE_URL(base_url)" ;;
        urlenv:*) local v="${ep#urlenv:}"; base_url="${!v:-}"; names="$names ANTHROPIC_BASE_URL(env:$v)" ;;
    esac
    case "$cred" in
        env:*)    local c="${cred#env:}"; api_key="${!c:-}"; names="$names ANTHROPIC_API_KEY(env:$c)" ;;
    esac
    rb_journal "probe_launch_env" "profile '$id': wired${names:- nothing (backend login mode)}; tool canary=$tools"

    local nonce expected
    nonce=$(printf '%s:%s:%s:%s' "$id" "$gen" "$$" "$(date -u +%s)" \
        | { command -v shasum >/dev/null 2>&1 && shasum -a 256 || sha256sum; } \
        | cut -c1-20)
    expected="${RB_MARKER}:${nonce}"
    rb_prompt "$tools" "$expected" > "$wd/prompt.txt"
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
    # HARD BOUND. A probe talks to a provider that may hang; an
    # unbounded one hangs `routing tick`, and a scheduled tick that
    # never returns stops every profile from ever recovering.
    # ca_run_bounded (#242 C2) is the repo's proven bounded runner:
    # own process group, TERM then KILL, escalation allowed to
    # complete, 124 on expiry and 125 when the bound could not be
    # established. Both are already terminal in the cascade below —
    # 124 is "cut off with no usable evidence", never provider
    # failure. Credentials go through the CHILD ENVIRONMENT, never the
    # command string visible in the process argv.
    #
    # The child is UNTRUSTED provider code. Give any routing libraries
    # it happens to source private per-probe paths, not unset variables
    # that fall back to the real files under $HOME. This removes the
    # active accounting/state paths from its inherited capabilities;
    # it is not an OS sandbox against a malicious same-user process
    # that independently guesses host paths.
    local child_cmd
    child_cmd="cd $(printf '%q' "$wd") && exec bash -c $(printf '%q' "$cmd") < $(printf '%q' "$wd/prompt.txt") 2> $(printf '%q' "$stderr_file")"
    (
      export CCT_ROUTING_PROBE_LEDGER="$child_private/probe-ledger.json"
      export CCT_ROUTING_STATE="$child_private/state.json"
      export CCT_ROUTING_TICK_LOCK="$child_private/tick.lock"
      export CCT_ROUTING_REGISTRY="$child_private/registry.toml"
      export CCT_SUPERVISOR_DIR="$child_private/supervisor"
      export CCT_ROUTING_ARTIFACT_DIR="$child_private/artifacts"
      export CCT_PROBE=1 CCT_PROBE_PROFILE="$id" CCT_PROBE_MODEL="$model"
      export CCT_PROBE_TOOL_FILE="$RB_TOOL_FILE"
      [[ -n "$base_url" ]] && export ANTHROPIC_BASE_URL="$base_url"
      [[ -n "$api_key" ]] && export ANTHROPIC_API_KEY="$api_key"
      ca_run_bounded "$RB_TIMEOUT_SEC" "$child_cmd" "$stdout_file"
    )
    rc=$?
    # VERIFY the reservation survived the child. Rebinding the routing
    # paths is the defence; confirming the row is still there is
    # the proof — a probe whose accounting vanished is unverifiable,
    # never a pass.
    if ! jq -e --arg p "$id" --argjson g "$gen" \
           '[.probes[] | select(.profile == $p and .generation == $g)] | length > 0' \
           "$RB_LEDGER" >/dev/null 2>&1; then
        RB_OUTCOME="probe_unverifiable"
        RB_DETAIL="the probe's accounting reservation is gone after execution — refusing to report a result for an unaccounted probe"
        [[ "$had_errexit" -eq 1 ]] && set -e
        rb_journal "probe_unverifiable" "profile '$id': $RB_DETAIL"
        printf '%s\t%s\t%s\n' "$RB_OUTCOME" "$RB_DETAIL" "$RB_EVIDENCE"
        rb_probe_cleanup "$wd"
        return 0
    fi
    [[ "$had_errexit" -eq 1 ]] && set -e

    # ── step 4: scrub BEFORE anything persists or is classified
    local content
    if [[ -n "$api_key" ]]; then
        content="$(cat "$stdout_file" 2>/dev/null)"
        printf '%s\n' "${content//"$api_key"/[REDACTED:ANTHROPIC_API_KEY]}" > "$stdout_file"
        content="$(cat "$stderr_file" 2>/dev/null)"
        printf '%s\n' "${content//"$api_key"/[REDACTED:ANTHROPIC_API_KEY]}" > "$stderr_file"
    fi
    { cat "$stdout_file" 2>/dev/null || true; cat "$stderr_file" 2>/dev/null || true; } > "$capture"
    RB_TRANSCRIPT="$capture"

    # reconcile the estimate with a measured cost when the backend
    # reports one (same ledger row, never a second debit)
    local measured
    measured=$(rb_measured_cost "$stdout_file")
    if [[ -n "$measured" ]]; then
        RB_COST="$measured"
        if ! rb_debit "$id" "$gen" "$measured" false; then
            RB_OUTCOME="probe_unverifiable"
            RB_DETAIL="the measured probe cost \$$measured could not replace its estimate — refusing a result whose spend cannot be enforced"
            rb_journal "probe_unverifiable" "profile '$id': $RB_DETAIL"
            printf '%s\t%s\t%s\n' "$RB_OUTCOME" "$RB_DETAIL" "$RB_EVIDENCE"
            rb_probe_cleanup "$wd"
            return 0
        fi
    else
        RB_COST="$RB_ESTIMATE_USD"
        rb_journal "probe_cost_estimated" "profile '$id': cost unmeasurable — debited the named estimate \$$RB_ESTIMATE_USD (RB_ESTIMATE_USD), flagged estimated"
    fi

    # ── step 5: classification — evidence only
    local have_marker=0 have_tool=0 response
    response=$(rb_result_text "$stdout_file")
    if [[ "$response" == "$expected" ]]; then have_marker=1; fi
    if [[ -s "$RB_TOOL_FILE" ]] && grep -q "$RB_TOOL_MARKER" "$RB_TOOL_FILE" 2>/dev/null; then have_tool=1; fi

    # A's frozen classifier is run ONCE over the SAME scrubbed capture
    # that the cascade below reads, and BOTH the failure class and the
    # provider RECOVERY TIMING come out of that single evaluation. The
    # timing is the whole point of the precedence chain in
    # routing-recovery.sh: a provider that says `Retry-After: 900` has
    # told us when it will be back, and a computed backoff must never
    # overrule it. Discarding this here would make rd_next_probe_at's
    # top three sources dead code at the only call site that matters.
    # Object shorthand (no `//`) keeps absent keys as an explicit
    # null and cannot widen a false.
    local cls
    cls=$(rr_classify "$rc" "$capture" 2>/dev/null || echo '{}')
    RB_EVIDENCE=$(jq -c '{reset_at, retry_after_sec, rate_limits_resets_at}' <<< "$cls" 2>/dev/null || echo '{}')
    [[ -n "$RB_EVIDENCE" ]] || RB_EVIDENCE="{}"
    # A's classifier reads headers and message text; it does not read
    # the SUBSCRIPTION usage block, so rate_limits_resets_at would be
    # permanently null and the third precedence source dead on every
    # real probe. Recover it from the SAME capture: the earliest
    # resets_at across the rate_limits map (the first moment any
    # window reopens). Only fills a gap — never overrides what the
    # classifier already established from the response itself.
    local rl rl_all
    rl_all=$(rb_json_records "$stdout_file" | jq -c -s 'map(if type == "array" then .[] else . end)
                     | [.[] | .rate_limits? | objects | .[] | objects | .resets_at
                       | select(type == "string")] | sort' 2>/dev/null || echo '[]')
    [[ -n "$rl_all" ]] || rl_all='[]'
    rl=$(jq -r 'if length == 0 then empty else .[0] end' <<< "$rl_all" 2>/dev/null || true)
    if [[ -n "$rl" ]]; then
        RB_EVIDENCE=$(jq -c --arg r "$rl" '.rate_limits_resets_at = $r' <<< "$RB_EVIDENCE")
        # A's classifier takes reset_at as the FIRST ISO timestamp
        # anywhere in the capture. When that value is simply one of the
        # rate_limits entries, the regex and this structured read are
        # looking at the SAME bytes — and the structured read is the
        # better parse: it knows which window reopens FIRST, where the
        # regex only knows which one was printed first. Yield to it in
        # exactly that case, and never otherwise: a reset_at that came
        # from a header or message is independent evidence and keeps
        # its higher precedence.
        if jq -e --argjson all "$rl_all" \
             '.reset_at != null and (.reset_at as $r | $all | index($r) != null)' \
             >/dev/null 2>&1 <<< "$RB_EVIDENCE"; then
            RB_EVIDENCE=$(jq -c '.reset_at = null' <<< "$RB_EVIDENCE")
            rb_journal "probe_rate_limit_window" "profile '$id': subscription rate_limits reopen at $rl — the textual reset_at was one of these same windows, so the structured (earliest) read is used"
        else
            rb_journal "probe_rate_limit_window" "profile '$id': subscription rate_limits reopen at $rl (read from the probe capture)"
        fi
    fi

    if [[ "$rc" -eq 125 ]]; then
        RB_OUTCOME="probe_unverifiable"
        RB_DETAIL="the probe bound could not be established or its process group could not be reaped — no evidence, and never a provider verdict"
    elif [[ "$rc" -eq 124 || "$rc" -eq 137 ]]; then
        RB_OUTCOME="probe_unverifiable"
        RB_DETAIL="the canary was cut off after ${RB_TIMEOUT_SEC}s (exit $rc) with no usable evidence — a missing answer is not provider failure"
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
        cause=$(jq -r 'if .failure_class == null then "unknown" else .failure_class end' <<< "$cls" 2>/dev/null || echo "unknown")
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
    printf '%s\t%s\t%s\n' "$RB_OUTCOME" "$RB_DETAIL" "$RB_EVIDENCE"
    rb_probe_cleanup "$wd"
    return 0
}
