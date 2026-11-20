#!/usr/bin/env bash
# claude-code.sh — how a catalog binding becomes a Claude Code launch
# (#479; #400 FR-20 and FR-30). Sourced after llm-catalog.sh, with a
# parsed and VALID catalog.
#
# Claude Code reads its provider, credential and model from the
# environment of its own process, so a launch is a set of variables to
# SET and a set to REMOVE in that one process:
#   - an api endpoint: the base URL, one credential, every model alias
#     (so alias and background requests stay on the endpoint), the
#     endpoint's quirks, the binding's tuning;
#   - a managed provider (Claude Code's own login): the model only, and
#     every gateway variable removed, so the session is Anthropic's even
#     when the shell that started it was configured for a gateway.
# Removed in both cases: the credential the plan does not use, custom
# headers, the provider switches with their base URLs, the subagent
# model override, and the tuning variables the binding does not set, so
# nothing the user did not select can redirect the session, reach the
# endpoint, or tune a session on one model with another model's values.
#
# The plan (llm_cc_plan) holds NAMES and non-secret literals only. A
# credential's value is read by llm_cc_apply alone, in the process that
# is about to exec claude, and goes nowhere but that process's
# environment: never an argument, a file or an output.
#
# The variable names are the ones the installed Claude Code (2.1.329)
# carries; ANTHROPIC_DEFAULT_FABLE_MODEL is among them.
#
# bash 3.2 compatible, safe under `set -e` and `set -u`.

LLM_CC_HARNESS="claude-code"
LLM_CC_PROTOCOL="anthropic-messages"
# Sent as the bearer token when an endpoint takes no credential. Without
# any credential variable Claude Code would fall back to its own login
# and send that to the endpoint.
LLM_CC_NO_CREDENTIAL_TOKEN="none"

LLM_CC_VAR_BASE_URL="ANTHROPIC_BASE_URL"
LLM_CC_VAR_BEARER="ANTHROPIC_AUTH_TOKEN"
LLM_CC_VAR_API_KEY="ANTHROPIC_API_KEY"
LLM_CC_VAR_MODEL="ANTHROPIC_MODEL"
# Aliases that mean "the main model" and "the small, fast model".
LLM_CC_VARS_MAIN_ALIASES="ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_FABLE_MODEL"
LLM_CC_VARS_SMALL_ALIASES="ANTHROPIC_DEFAULT_HAIKU_MODEL ANTHROPIC_SMALL_FAST_MODEL"
LLM_CC_VAR_MAX_OUTPUT="CLAUDE_CODE_MAX_OUTPUT_TOKENS"
LLM_CC_VAR_AUTO_COMPACT="CLAUDE_CODE_AUTO_COMPACT_WINDOW"
LLM_CC_VAR_EFFORT="CLAUDE_CODE_EFFORT_LEVEL"
# Removed from every selected launch.
LLM_CC_VARS_ALWAYS_CLEARED="ANTHROPIC_CUSTOM_HEADERS ANTHROPIC_DEFAULT_MODEL CLAUDE_CODE_SUBAGENT_MODEL CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX CLAUDE_CODE_USE_FOUNDRY CLAUDE_CODE_USE_ANTHROPIC_AWS CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD CLAUDE_CODE_USE_MANTLE ANTHROPIC_BEDROCK_BASE_URL ANTHROPIC_BEDROCK_MANTLE_BASE_URL ANTHROPIC_VERTEX_BASE_URL ANTHROPIC_FOUNDRY_BASE_URL ANTHROPIC_AWS_BASE_URL ANTHROPIC_GOOGLE_CLOUD_BASE_URL"

_llm_cc_set() {  # <NAME> lit|env <value, or the NAME of the variable to copy>
    LLM_CC_ASSIGN="${LLM_CC_ASSIGN}$1${CT_US}$2${CT_US}$3"$'\n'
    LLM_CC_SET="${LLM_CC_SET}$1 "
}

# llm_cc_plan <binding-id>
# Sets:
#   LLM_CC_STATE   unverified (launchable; nothing has probed it) |
#                  unsupported | unavailable
#   LLM_CC_REASON  why it is not launchable
#   LLM_CC_SET     the NAMES the launch sets, space-separated
#   LLM_CC_CLEAR   the NAMES the launch removes, space-separated
#   LLM_CC_ASSIGN  NAME<US>lit|env<US>payload records for llm_cc_apply
#   LLM_CC_LABEL   "<provider> · <model> · <origin>" for a notice
#   LLM_CC_QUIRK_DECLARED  1 when the endpoint declares rejects-dynamic-tools
# Always returns 0; the state says whether to launch.
llm_cc_plan() {
    local b="bindings.$1" l e="" lp pname pkind ep mode="" header="" proto model small cred="" v name
    local clear="$LLM_CC_VARS_ALWAYS_CLEARED" origin=""
    LLM_CC_STATE="unverified"
    LLM_CC_REASON=""
    LLM_CC_SET=""
    LLM_CC_CLEAR=""
    LLM_CC_ASSIGN=""
    LLM_CC_LABEL=""
    LLM_CC_QUIRK_DECLARED=0

    l=$(lc_get "$b" llm) || l=""
    model=$(lc_get "llms.$l" model) || model=""
    lp=$(lc_get "llms.$l" provider) || lp=""
    pkind=$(lc_get "providers.$lp" kind) || pkind=""
    pname=$(lc_get "providers.$lp" display_name) || pname="$lp"

    _llm_cc_set "$LLM_CC_VAR_MODEL" lit "$model"
    if [[ "$pkind" == "managed" ]]; then
        clear="$clear $LLM_CC_VAR_BASE_URL $LLM_CC_VAR_BEARER $LLM_CC_VARS_MAIN_ALIASES $LLM_CC_VARS_SMALL_ALIASES"
        LLM_CC_LABEL="$pname · $model · Claude Code's own login"
    else
        e=$(lc_get "$b" endpoint) || e=""
        proto=$(lc_get "endpoints.$e" protocol) || proto=""
        header=$(lc_get "endpoints.$e" auth_header) || header=""
        ep=$(lc_get "endpoints.$e" provider) || ep=""
        mode=$(lc_get "providers.$ep" credential_mode) || mode=""
        cred=$(lc_get "providers.$ep" credential_env) || cred=""

        if lc_endpoint_url "$e"; then
            origin=$(rt_sanitize_origin "$LC_URL")
            if name=$(lc_get "endpoints.$e" base_url_env); then
                _llm_cc_set "$LLM_CC_VAR_BASE_URL" env "$name"
            else
                _llm_cc_set "$LLM_CC_VAR_BASE_URL" lit "$LC_URL"
            fi
        else
            LLM_CC_STATE="unavailable"
            LLM_CC_REASON="$LC_URL_ERR"
        fi
        LLM_CC_LABEL="$pname · $model · ${origin:-endpoint $e}"

        case "$header" in
            x-api-key)
                _llm_cc_set "$LLM_CC_VAR_API_KEY" env "$cred"
                clear="$clear $LLM_CC_VAR_BEARER" ;;
            bearer)
                _llm_cc_set "$LLM_CC_VAR_BEARER" env "$cred"
                clear="$clear $LLM_CC_VAR_API_KEY" ;;
            *)
                _llm_cc_set "$LLM_CC_VAR_BEARER" lit "$LLM_CC_NO_CREDENTIAL_TOKEN"
                clear="$clear $LLM_CC_VAR_API_KEY" ;;
        esac
        if [[ "$mode" == "env" && "$LLM_CC_STATE" == "unverified" ]]; then
            # Checked before the indirect expansion, which evaluates a subscript.
            if [[ ! "$cred" =~ $LC_ENV_NAME_RE ]]; then
                LLM_CC_STATE="unavailable"
                LLM_CC_REASON="provider '$ep' names no credential variable"
            elif [[ -z "${!cred:-}" ]]; then
                LLM_CC_STATE="unavailable"
                LLM_CC_REASON="credential variable $cred is not set"
            fi
        fi

        small=$(lc_get "$b" small_fast_model) || small="$model"
        for v in $LLM_CC_VARS_MAIN_ALIASES; do _llm_cc_set "$v" lit "$model"; done
        for v in $LLM_CC_VARS_SMALL_ALIASES; do _llm_cc_set "$v" lit "$small"; done

        if lc_array_elems "endpoints.$e" quirks 2>/dev/null | grep -qx "rejects-dynamic-tools"; then
            LLM_CC_QUIRK_DECLARED=1
            _llm_cc_set CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS lit 1
            _llm_cc_set ENABLE_TOOL_SEARCH lit false
            _llm_cc_set DISABLE_FEEDBACK_COMMAND lit 1
        fi

        # The protocol decides last, so its reason is the one reported.
        if [[ "$proto" != "$LLM_CC_PROTOCOL" ]]; then
            LLM_CC_STATE="unsupported"
            LLM_CC_REASON="endpoint '$e' speaks $proto, $LLM_CC_HARNESS speaks $LLM_CC_PROTOCOL"
        fi
    fi

    # Tuning the binding owns: set from it, otherwise removed, so a value
    # exported for one model never tunes a session on another.
    if v=$(lc_get "$b" max_output_tokens); then _llm_cc_set "$LLM_CC_VAR_MAX_OUTPUT" lit "$v"; else clear="$clear $LLM_CC_VAR_MAX_OUTPUT"; fi
    if v=$(lc_get "$b" auto_compact_window); then _llm_cc_set "$LLM_CC_VAR_AUTO_COMPACT" lit "$v"; else clear="$clear $LLM_CC_VAR_AUTO_COMPACT"; fi
    if v=$(lc_get "$b" reasoning_effort); then _llm_cc_set "$LLM_CC_VAR_EFFORT" lit "$v"; else clear="$clear $LLM_CC_VAR_EFFORT"; fi

    LLM_CC_SET="${LLM_CC_SET% }"
    LLM_CC_CLEAR="$clear"
    return 0
}

# llm_cc_settings_conflicts <project-dir>
# Claude Code applies a settings file's env block over the environment
# it was started with, so a variable the plan sets or removes that a
# settings file also sets would silently undo the selection. Prints
# "<file>: <NAME>" for each one. Returns 0 none, 1 some, 2 not checked
# (jq is missing).
llm_cc_settings_conflicts() {
    local project="$1" f name found=0
    command -v jq >/dev/null 2>&1 || return 2
    for f in "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json" \
             "$project/.claude/settings.json" \
             "$project/.claude/settings.local.json"; do
        [[ -f "$f" ]] || continue
        while IFS= read -r name; do
            [[ -z "$name" ]] && continue
            case " $LLM_CC_SET $LLM_CC_CLEAR " in
                *" $name "*) printf '%s: %s\n' "$f" "$name"; found=1 ;;
            esac
        done <<< "$(jq -r '(.env // {}) | keys[]' "$f" 2>/dev/null || true)"
    done
    [[ $found -eq 0 ]]
}

# llm_cc_apply
# Applies the plan to THIS process's environment; call it immediately
# before exec. Every value is read first, because a variable the plan
# copies from may itself be on the removal list.
llm_cc_apply() {
    local rec name kind payload n=0 i
    local names=() values=()
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        name="${rec%%"$CT_US"*}"; rec="${rec#*"$CT_US"}"
        kind="${rec%%"$CT_US"*}"; payload="${rec#*"$CT_US"}"
        names[n]="$name"
        if [[ "$kind" != "env" ]]; then
            values[n]="$payload"
        elif [[ "$payload" =~ $LC_ENV_NAME_RE ]]; then
            values[n]="${!payload:-}"
        else
            values[n]=""
        fi
        n=$((n + 1))
    done <<< "$LLM_CC_ASSIGN"
    for name in $LLM_CC_CLEAR; do unset "$name"; done
    i=0
    while [[ $i -lt $n ]]; do
        export "${names[i]}=${values[i]}"
        i=$((i + 1))
    done
    return 0
}
