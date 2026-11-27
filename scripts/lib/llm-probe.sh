#!/usr/bin/env bash
# llm-probe.sh — the behavioral probe of a catalog target on a harness
# (#400 FR-15, FR-16; slice S3): what `cct llm test` runs.
#
# lp_probe <harness> <target> runs the harness headless through the
# resolved plan, with the environment a launch of that target gets, on a
# canary, and records the per-capability matrix:
#   - the canary asks for one shell command through the Bash tool, which
#     writes the marker file and prints a nonce from a file only the tool
#     can read, and for one reply line: the canary's marker, the token the
#     appended system prompt gives, and what the command printed;
#   - when the llm declares image input, a second run puts a small image
#     in the prompt and asks for its colour.
# Each capability is pass, fail, unverifiable or not_applicable (FR-15).
# The run's outcome is pass, fail (behavioral evidence: a required
# capability that ran and did not do what was asked, or a request shape
# the endpoint rejected), unavailable (the credential was refused), or
# unverifiable (a timeout, a crash, unparseable output, a transient
# error). Only pass and fail are conclusive (FR-13, FR-16).
#
# Sets LP_OUTCOME, LP_MATRIX (JSON), LP_DETAIL and LP_REDACTED (the reply
# or error, with the credential's value, the probe directory and the home
# directory taken out), and leaves lcm_state's LCM_* and the resolver's
# LR_* set. Returns 0 when the run was recorded; 1 when it could not run
# (LP_ERR says why; LP_REFUSED=1 when the target's state refuses it, as a
# launch would); 2 when its record could not be written.
#
# The canary primitives are cct-canary.sh's (D6). Each run is bounded by
# ca_run_bounded, the routing probe's runner, on its own process group:
# TERM after CCT_LLM_PROBE_TIMEOUT_SEC (default 120), then KILL ten seconds
# later. A caller that can be interrupted sets CA_OWNER_ID and
# CA_ACTIVE_GROUP_FILE, and calls lp_cleanup from its traps (cct llm test
# does). Test seam: CCT_LLM_PROBE_CMD replaces the harness executable; it
# receives the same environment and arguments.
#
# Needs llm-catalog.sh, llm-adapters/claude-code.sh, llm-resolve.sh,
# cct-statefile.sh and llm-compat.sh sourced first; jq.
#
# bash 3.2 compatible.

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cct-canary.sh"
if ! declare -F ca_run_bounded >/dev/null 2>&1; then
    # shellcheck source=/dev/null
    source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/conformance-app.sh"
fi

LP_TIMEOUT_DEFAULT_SEC=120
LP_KILL_GRACE_SEC=10
# The harness gives up on a refused credential after this many retries,
# rather than retrying for minutes before the bound ends it.
LP_MAX_RETRIES=1
LP_SYSTEM_MARKER="CCT_SYS_OK"
LP_RESULT_MARKER="CCT_RESULT"
LP_EXCERPT_CHARS=300
# The canary's one command is a script in the probe's directory, and the
# harness may run that command and nothing else: the endpoint is the model,
# and could ask for more in the same tool call. No mode accepts edits.
LP_CANARY_SCRIPT="canary.sh"
LP_CANARY_COMMAND="sh $LP_CANARY_SCRIPT"
LP_ALLOWED_TOOLS="Bash($LP_CANARY_COMMAND)"
# A 400 or 422 is a rejected request shape only when its message says so: an
# exhausted balance or an unknown model is a 400 too, and says nothing about
# whether the harness can speak to the endpoint (FR-13).
LP_SHAPE_RE='(unsupported|unrecognized|unknown|unexpected|invalid|not supported|not permitted|not allowed)[^.]{0,40}(parameter|argument|field|property|input|content block|block type|tool|header|beta)|extra (inputs|fields) (are|is) not permitted|validation error|should be a valid|does not match any of the expected|tool_reference|input_schema'
LP_NOT_SHAPE_RE='credit|balance|billing|quota|payment|insufficient|no such model|(unknown|invalid|unsupported) model|model[^.]{0,40}(not found|does not exist|not available|unknown|invalid|unsupported)'
# A 32x32 red PNG, and its colour, for the image_input check.
LP_IMAGE_PNG_B64="iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAJ0lEQVR42u3NsQkAAAjAsP7/tF7hIASyp6lTCQQCgUAgEAgEgi/BAjLD/C5w/SM9AAAAAElFTkSuQmCC"
LP_IMAGE_COLOUR="red"

# The harness's process group is reaped, and the run's subshell told to
# stop: the bounded runner then reaps the group itself, ends its watchdog
# and removes its own directory. Both are repeated while the subshell lives,
# for a signal that lands before the harness has registered its group (a
# gap of milliseconds; a harness that registered more than two seconds
# later would be left to its bound). Then the probe's directory goes.
LP_CLEANUP_TRIES=10   # x 0.2 s
lp_cleanup() {
    local i=0
    if [[ -n "${LP_RUN_PID:-}" ]]; then
        while [[ "$i" -lt "$LP_CLEANUP_TRIES" ]]; do
            ca_active_cleanup >/dev/null 2>&1 || true
            kill -TERM "$LP_RUN_PID" 2>/dev/null || break
            sleep 0.2
            i=$((i + 1))
        done
        wait "$LP_RUN_PID" 2>/dev/null || true
    else
        ca_active_cleanup >/dev/null 2>&1 || true
    fi
    LP_RUN_PID=""
    if [[ -n "${LP_WD:-}" && -d "$LP_WD" ]]; then rm -rf "$LP_WD"; fi
    LP_WD=""
}

# The variable the plan copies the credential from, when it uses one.
_lp_credential_var() {
    local rec name kind payload
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        name="${rec%%"$CT_US"*}"; rec="${rec#*"$CT_US"}"
        kind="${rec%%"$CT_US"*}"; payload="${rec#*"$CT_US"}"
        case "$name" in
            "$LLM_CC_VAR_API_KEY"|"$LLM_CC_VAR_BEARER")
                [[ "$kind" == "env" ]] && { printf '%s\n' "$payload"; return 0; } ;;
        esac
    done <<< "$LLM_CC_ASSIGN"
    return 0
}

# One bounded run of the harness: <stdin-file> <stdout-file> <stderr-file>
# <harness arguments...>. In a subshell, so that the plan's environment
# reaches the harness alone, waited for in the background, so that a signal
# to the caller is acted on at once rather than when the run ends. The
# subshell ignores HUP (and, as a background command, INT), and a TERM only
# stops it waiting: either way the bounded runner reaps the harness, ends
# its watchdog and removes its directory before the subshell ends. A TERM
# that comes before the runner starts stops the run from starting. The
# harness keeps the default TERM, since a caught signal is not inherited
# across exec. Returns ca_run_bounded's status.
_lp_run() {
    local in="$1" out="$2" err="$3" cmd a child rc=0
    shift 3
    if [[ -n "${CCT_LLM_PROBE_CMD:-}" ]]; then cmd="$CCT_LLM_PROBE_CMD"; else cmd=$(printf '%q' "$LLM_CC_EXECUTABLE"); fi
    for a in "$@"; do cmd="$cmd $(printf '%q' "$a")"; done
    child="cd $(printf '%q' "$LP_WD") && exec $cmd < $(printf '%q' "$in") 2> $(printf '%q' "$err")"
    ( trap '' HUP
      lp_stop=""
      trap 'lp_stop=1' TERM
      llm_cc_apply
      export CLAUDE_CODE_MAX_RETRIES="$LP_MAX_RETRIES"
      [[ -z "$lp_stop" ]] || exit 143
      ca_run_bounded "$LP_TIMEOUT" "$child" "$out" "$LP_KILL_GRACE_SEC" ) &
    LP_RUN_PID=$!
    wait "$LP_RUN_PID" || rc=$?
    LP_RUN_PID=""
    return "$rc"
}

# What a run's machine-readable output says, as one JSON object.
_lp_summary() {  # <stdout-file>
    cn_json_records "$1" | jq -cs '
      map(if type == "array" then .[] else . end) | map(select(type == "object")) as $r
      | ([ $r[] | select(.type == "result") ] | last) as $res
      | ($res.result? // "" | tostring) as $text
      | { parsed: ($res != null),
          is_error: ($res.is_error? == true),
          status: ([ $text | capture("API Error: (?<s>[0-9]{3})")? | .s | tonumber ] | first // null),
          models: [ $r[] | select(.type == "assistant") | .message.model? | strings
                    | select(. != "<synthetic>") ] | unique,
          thinking: any($r[]; .type == "assistant"
                      and ((.message.content? // []) | any(.type? == "thinking" or .type? == "redacted_thinking"))),
          auth_refused: any($r[]; (.type == "system" and .subtype? == "api_retry"
                                  and (.error_status? == 401 or .error_status? == 403
                                       or .error? == "authentication_failed"))
                               or (.type == "assistant" and .error? == "authentication_failed")),
          denied: ($res.permission_denials? // [] | length),
          streamed: any($r[]; .type == "stream_event" and .event.type? == "content_block_delta"),
          out_tokens: [ $r[] | select(.type == "stream_event" and .event.type? == "message_delta")
                        | .event.usage.output_tokens? | numbers ] }' 2>/dev/null
}

_lp_sv() { jq -r "$1" <<< "$LP_S"; }   # one field of the run's summary

_lp_redact() {  # <text>: the credential, the endpoint's path, the probe directory and the home directory taken out
    local t="$1" tilde="~"   # a literal "~" in the replacement would be tilde-expanded
    [[ -n "${LP_SECRET:-}" ]] && t="${t//"$LP_SECRET"/[REDACTED:$LP_SECRET_NAME]}"
    [[ -n "${LP_URL_PATH:-}" ]] && t="${t//"$LP_URL_PATH"/<endpoint-path>}"
    [[ -n "${LP_WD:-}" ]] && t="${t//"$LP_WD"/<probe-dir>}"
    [[ -n "${HOME:-}" && "$HOME" != "/" ]] && t="${t//"$HOME"/$tilde}"
    t=$(printf '%s' "$t" | tr -d '\000-\010\013-\037' | tr '\n\t' '  ')
    printf '%s' "${t:0:$LP_EXCERPT_CHARS}"
}

lp_probe() {
    local h="$1" target="$2" rc=0 seed n1 n2 n3 n4 sys reply img_reply img_s cred
    local auth model streaming system tool_call tool_result parsing clean limits reasoning image
    local required c v failed="" open="" max="" tmp_out want p img_rc img_err
    LP_OUTCOME="" LP_MATRIX="null" LP_DETAIL="" LP_REDACTED="" LP_ERR="" LP_REFUSED=0 LP_NOTES=""
    LP_SECRET="" LP_SECRET_NAME="" LP_URL_PATH=""

    LP_TIMEOUT="${CCT_LLM_PROBE_TIMEOUT_SEC:-$LP_TIMEOUT_DEFAULT_SEC}"
    if [[ ! "$LP_TIMEOUT" =~ ^[0-9]+$ || "$LP_TIMEOUT" -lt 1 ]]; then
        LP_ERR="CCT_LLM_PROBE_TIMEOUT_SEC='$LP_TIMEOUT' is not a positive whole number of seconds; refusing to run an unbounded probe"
        return 1
    fi

    lcm_state "$h" "$target" || rc=$?
    if [[ "$rc" -ne 0 ]]; then LP_ERR="$LCM_ERR"; return 1; fi
    case "$LCM_STATE" in
        unsupported|unavailable)
            LP_REFUSED=1
            LP_ERR="$LCM_STATE: $LCM_REASON"
            return 1 ;;
    esac

    if ! LP_WD=$(mktemp -d "${TMPDIR:-/tmp}/cct-llm-probe.XXXXXX"); then
        LP_WD=""
        LP_ERR="the probe's private directory could not be created"
        return 1
    fi
    # A settings file's env block wins over the environment claude starts
    # with, as for a launch: one that would send another credential, reach
    # another endpoint or ask for another model refuses the test, which
    # would measure something else; tuning is said (FR-30). The run's
    # directory holds no project settings, so the user's file is the one.
    rc=0
    llm_cc_settings_conflicts "$LP_WD" || rc=$?
    if [[ "$rc" -eq 1 ]]; then
        LP_REFUSED=1
        LP_ERR="a Claude Code settings file sets a variable this test must control ($(printf '%s' "$LLM_CC_SETTINGS_REFUSED" | paste -sd ';' - | sed 's/;/; /g')): Claude Code applies its env block over the test's environment; remove those keys from it"
        lp_cleanup
        return 1
    fi
    LP_NOTES="$LLM_CC_SETTINGS_NOTED"
    cred=$(_lp_credential_var)
    if [[ -n "$cred" && "$cred" =~ $LC_ENV_NAME_RE ]]; then LP_SECRET="${!cred:-}"; LP_SECRET_NAME="$cred"; fi
    # The endpoint's path is kept out of the record like its credential: an
    # error that echoes the request path would carry it (FR-15).
    if [[ -n "$LR_ENDPOINT_ID" ]] && lc_endpoint_url "$LR_ENDPOINT_ID"; then
        p="${LC_URL#*://}"
        if [[ "$p" == */* ]]; then p="/${p#*/}"; p="${p%/}"; [[ -n "$p" ]] && LP_URL_PATH="$p"; fi
    fi

    seed="$h:$target:$$:$(date -u +%s)"
    n1=$(cn_nonce "$seed:marker"); n2=$(cn_nonce "$seed:system"); n3=$(cn_nonce "$seed:result")
    sys="The canary token is $LP_SYSTEM_MARKER:$n2."
    printf '%s:%s\n' "$LP_RESULT_MARKER" "$n3" > "$LP_WD/result.txt"
    # Relative paths: the harness runs in the probe's directory, and no path
    # reaches the prompt, whatever characters the directory's holds.
    printf '%s\n' "printf %s $CN_TOOL_MARKER > tool-canary.txt" "cat result.txt" > "$LP_WD/$LP_CANARY_SCRIPT"
    cn_prompt 1 "exactly one line: $CN_MARKER:$n1, then a space and the canary token your system instructions give, then a space and the text the command printed" \
        "$LP_CANARY_COMMAND" > "$LP_WD/prompt.txt"

    rc=0
    _lp_run "$LP_WD/prompt.txt" "$LP_WD/stdout.jsonl" "$LP_WD/stderr.txt" \
        -p --output-format stream-json --verbose --include-partial-messages --no-session-persistence \
        --append-system-prompt "$sys" --allowedTools "$LP_ALLOWED_TOOLS" || rc=$?
    cn_scrub "$LP_WD/stdout.jsonl" "$LP_SECRET" "$LP_SECRET_NAME"
    cn_scrub "$LP_WD/stderr.txt" "$LP_SECRET" "$LP_SECRET_NAME"
    LP_S=$(_lp_summary "$LP_WD/stdout.jsonl")
    [[ -n "$LP_S" ]] || LP_S='{"parsed":false,"is_error":false,"status":null,"models":[],"thinking":false,"auth_refused":false,"denied":0,"streamed":false,"out_tokens":[]}'
    reply=$(cn_result_text "$LP_WD/stdout.jsonl")

    local replied=0 marker_ok=0 tool_ok=0 timed_out=0 crashed=0 auth_refused=0 shape=0 is_error parsed status
    [[ "$(_lp_sv '.models | length')" -gt 0 ]] && replied=1
    [[ "$reply" == *"$CN_MARKER:$n1"* ]] && marker_ok=1
    cn_tool_ran "$LP_WD/tool-canary.txt" "$CN_TOOL_MARKER" && tool_ok=1
    [[ "$rc" -eq 124 || "$rc" -eq 125 || "$rc" -eq 137 ]] && timed_out=1
    parsed=$(_lp_sv '.parsed'); is_error=$(_lp_sv '.is_error'); status=$(_lp_sv '.status // empty')
    # Claude Code exits 0 with its answer and 1 with an error it reports;
    # any other exit, or 1 with an answer, is a crash, which decides nothing
    # whatever was printed before it (FR-13).
    if [[ "$timed_out" -eq 0 ]] && { [[ "$rc" -ne 0 && "$rc" -ne 1 ]] || [[ "$rc" -eq 1 && "$is_error" != "true" ]]; }; then crashed=1; fi
    if [[ "$(_lp_sv '.auth_refused')" == "true" || "$status" == "401" || "$status" == "403" ]]; then auth_refused=1; fi
    if [[ "$is_error" == "true" && ( "$status" == "400" || "$status" == "422" ) && "$auth_refused" -eq 0 ]] \
       && grep -qiE "$LP_SHAPE_RE" <<< "$reply" && ! grep -qiE "$LP_NOT_SHAPE_RE" <<< "$reply"; then shape=1; fi

    if [[ "$auth_refused" -eq 1 ]]; then auth=fail; elif [[ "$replied" -eq 1 ]]; then auth=pass; else auth=unverifiable; fi
    # Claude Code sends a model without its context suffix ("model[1m]" goes
    # out as "model"), and the endpoint reports what it was sent.
    # A name that only contains the requested one, or is contained in it (an
    # alias Claude Code resolved, a dated id), cannot be confirmed either
    # way: unverifiable, never fail.
    want="$LR_MODEL"
    if [[ "$want" =~ ^(.+)\[[0-9A-Za-z]+\]$ ]]; then want="${BASH_REMATCH[1]}"; fi
    if [[ "$replied" -eq 0 ]]; then model=unverifiable
    elif [[ "$(jq -r --arg m "$want" 'all(.models[]; . == $m)' <<< "$LP_S")" == "true" ]]; then model=pass
    elif [[ "$(jq -r --arg m "$want" '($m | ascii_downcase) as $w
            | all(.models[]; ascii_downcase as $r | ($r | contains($w)) or ($w | contains($r)))' <<< "$LP_S")" == "true" ]]; then model=unverifiable
    else model=fail; fi
    if [[ "$(_lp_sv '.streamed')" == "true" ]]; then streaming=pass
    elif [[ "$replied" -eq 1 ]]; then streaming=fail; else streaming=unverifiable; fi
    if [[ "$marker_ok" -eq 1 ]]; then
        if [[ "$reply" == *"$LP_SYSTEM_MARKER:$n2"* ]]; then system=pass; else system=fail; fi
    else system=unverifiable; fi
    if [[ "$tool_ok" -eq 1 ]]; then tool_call=pass
    elif [[ "$marker_ok" -eq 1 ]]; then tool_call=fail; else tool_call=unverifiable; fi
    if [[ "$tool_ok" -eq 1 && "$reply" == *"$LP_RESULT_MARKER:$n3"* ]]; then tool_result=pass
    elif [[ "$tool_ok" -eq 1 && "$marker_ok" -eq 1 ]]; then tool_result=fail; else tool_result=unverifiable; fi
    if [[ "$parsed" == "true" && "$is_error" != "true" ]]; then parsing=pass
    elif [[ "$shape" -eq 1 ]]; then parsing=fail; else parsing=unverifiable; fi
    if [[ "$timed_out" -eq 1 || "$crashed" -eq 1 ]]; then clean=fail
    elif [[ "$parsed" == "true" ]]; then clean=pass; else clean=fail; fi
    max=$(lc_get "bindings.$LR_BINDING" max_output_tokens 2>/dev/null) || max=""
    if [[ -z "$max" ]]; then limits=not_applicable
    elif [[ "$(_lp_sv '.out_tokens | length')" -eq 0 ]]; then limits=unverifiable
    elif [[ "$(jq -r --argjson m "$max" 'all(.out_tokens[]; . <= $m)' <<< "$LP_S")" == "true" ]]; then limits=pass
    else limits=fail; fi

    required=$(lcm_required "$h" "$LR_LLM")
    reasoning=not_applicable
    if grep -qx reasoning_control <<< "$required"; then
        if [[ "$(_lp_sv '.thinking')" == "true" ]]; then reasoning=pass
        elif [[ "$replied" -eq 1 ]]; then reasoning=fail; else reasoning=unverifiable; fi
    fi
    image=not_applicable
    if grep -qx image_input <<< "$required"; then
        image=unverifiable
        if [[ "$marker_ok" -eq 1 && "$timed_out" -eq 0 ]]; then
            n4=$(cn_nonce "$seed:image")
            jq -cn --arg t "$(cn_prompt 0 "exactly one line: $CN_MARKER:$n4, a space, and the colour of the image as one lowercase word")" \
                --arg d "$LP_IMAGE_PNG_B64" \
                '{type: "user", message: {role: "user", content: [{type: "text", text: $t},
                  {type: "image", source: {type: "base64", media_type: "image/png", data: $d}}]}}' > "$LP_WD/image.jsonl"
            tmp_out="$LP_WD/image-stdout.jsonl"
            img_rc=0
            _lp_run "$LP_WD/image.jsonl" "$tmp_out" "$LP_WD/image-stderr.txt" \
                -p --input-format stream-json --output-format stream-json --verbose --no-session-persistence || img_rc=$?
            cn_scrub "$tmp_out" "$LP_SECRET" "$LP_SECRET_NAME"
            img_err=$(_lp_summary "$tmp_out" | jq -r '.is_error' 2>/dev/null) || img_err=false
            # The image run is judged as the first: cut off, or a crash, and
            # nothing it printed counts (FR-13).
            if [[ "$img_rc" -eq 124 || "$img_rc" -eq 125 || "$img_rc" -eq 137 ]]; then
                clean=fail timed_out=1 rc="$img_rc"
            elif [[ "$img_rc" -ne 0 && "$img_rc" -ne 1 ]] || [[ "$img_rc" -eq 1 && "$img_err" != "true" ]]; then
                clean=fail crashed=1 rc="$img_rc"
            else
                img_reply=$(cn_result_text "$tmp_out")
                if [[ "$img_reply" == *"$CN_MARKER:$n4"* ]]; then
                    img_s=$(printf '%s' "$img_reply" | tr '[:upper:]' '[:lower:]')
                    if [[ " ${img_s//[^a-z0-9]/ } " == *" $LP_IMAGE_COLOUR "* ]]; then image=pass; else image=fail; fi
                fi
            fi
        fi
    fi

    LP_MATRIX=$(jq -nc --arg auth "$auth" --arg model "$model" --arg streaming "$streaming" \
        --arg system "$system" --arg tool_call "$tool_call" --arg tool_result "$tool_result" \
        --arg parsing "$parsing" --arg clean "$clean" --arg limits "$limits" \
        --arg reasoning "$reasoning" --arg image "$image" \
        '{auth: $auth, model_identity: $model, streaming: $streaming, system_prompt: $system,
          tool_call: $tool_call, tool_result: $tool_result, output_parsing: $parsing,
          clean_exit: $clean, limit_controls: $limits, reasoning_control: $reasoning,
          image_input: $image}')

    while IFS= read -r c; do
        [[ -z "$c" ]] && continue
        v=$(jq -r --arg c "$c" '.[$c] // "unverifiable"' <<< "$LP_MATRIX")
        case "$v" in
            fail) failed="${failed:+$failed, }$c" ;;
            unverifiable) open="${open:+$open, }$c" ;;
        esac
    done <<< "$required"

    if [[ "$auth_refused" -eq 1 ]]; then
        LP_OUTCOME="unavailable"
        LP_DETAIL="the endpoint refused the credential${status:+ (HTTP $status)}"
    elif [[ "$timed_out" -eq 1 ]]; then
        LP_OUTCOME="unverifiable"
        LP_DETAIL="cut off after ${LP_TIMEOUT}s (exit $rc), with no usable answer: never a verdict on the target"
    elif [[ "$crashed" -eq 1 ]]; then
        LP_OUTCOME="unverifiable"
        LP_DETAIL="$LLM_CC_EXECUTABLE ended with exit $rc: a crash, never a verdict on the target"
    elif [[ "$parsed" != "true" ]]; then
        LP_OUTCOME="unverifiable"
        LP_DETAIL="no result $LLM_CC_EXECUTABLE could report (exit $rc)"
    elif [[ "$shape" -eq 1 ]]; then
        LP_OUTCOME="fail"
        LP_DETAIL="the endpoint rejected the request shape (HTTP $status)"
    elif [[ "$is_error" == "true" ]]; then
        LP_OUTCOME="unverifiable"
        LP_DETAIL="the request did not complete${status:+ (HTTP $status)}: never a verdict on the target"
    elif [[ -n "$failed" ]]; then
        LP_OUTCOME="fail"
        LP_DETAIL="failed: $failed"
        if [[ "$(_lp_sv '.denied')" -gt 0 ]]; then
            LP_DETAIL="$LP_DETAIL (the endpoint asked to run more than the canary's command, and $LLM_CC_EXECUTABLE refused it)"
        fi
    elif [[ -n "$open" ]]; then
        LP_OUTCOME="unverifiable"
        LP_DETAIL="could not tell: $open"
    else
        LP_OUTCOME="pass"
        LP_DETAIL="passed every capability this binding needs"
    fi
    # The test seam replaces the harness, so its run is reported and recorded
    # and never decides the gate.
    if [[ -n "${CCT_LLM_PROBE_CMD:-}" ]]; then
        LP_DETAIL="CCT_LLM_PROBE_CMD ran in place of $LLM_CC_EXECUTABLE, so the run decides nothing (it was $LP_OUTCOME: $LP_DETAIL)"
        [[ "$LP_OUTCOME" == "pass" || "$LP_OUTCOME" == "fail" ]] && LP_OUTCOME="unverifiable"
    fi
    LP_REDACTED=$(_lp_redact "$reply")

    local attempt
    attempt=$(jq -nc --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg o "$LP_OUTCOME" --argjson m "$LP_MATRIX" \
        --argjson e "$LCM_EVIDENCE" --arg d "$LP_DETAIL" --arg r "$LP_REDACTED" \
        '{at: $at, outcome: $o, matrix: $m, evidence: ($e | {digest, launch_identity, options, harness_version, rule_version}),
          detail: $d, redacted: $r}')
    lp_cleanup
    if ! lcm_record_attempt "$h" "$LR_LLM" "$LR_BINDING" "$attempt"; then
        LP_ERR="$LCM_ERR"
        return 2
    fi
    return 0
}
