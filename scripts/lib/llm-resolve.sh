#!/usr/bin/env bash
# llm-resolve.sh — the one resolver for a --llm target (#400 FR-9, D15).
#
# A launch and its explanation must not disagree, so the launcher and the
# read-only commands (`cct harness explain`, `cct llm show`, `--json`) all
# resolve a target here: (harness, target) -> the binding, the harness
# adapter's plan (what the launch sets and removes, by NAME), its static
# state and, on request (lr_digests), three digests. Sourced after
# llm-catalog.sh and the harness adapters, with a parsed and VALID catalog.
#
# The digests (FR-9), each sha256 over canonical JSON. They take many jq
# runs, so they are computed only where they are read (explain and show;
# the session stamps of S4), never by a launch that reads none. None reads
# or includes a credential value, as the routing digest never reads
# credential_env:
#   catalog          provenance: the declared binding, llm, provider and
#                    endpoint tables, as written. Independent of the
#                    environment: a base_url_env is its NAME.
#   launch_identity  what the launch executes as: the resolved endpoint
#                    URL with its path, the protocol, the auth header, the
#                    credential's mode and variable NAME, the remote model
#                    and the quirks. It binds the full URL without
#                    exposing it, so two endpoints behind one origin
#                    differ here (FR-7). Reading the URL from base_url_env
#                    reads configuration, not a credential.
#   options          the tuning keys, which change how a session behaves
#                    on its target and never which target it reaches.
#
# bash 3.2 compatible; needs jq.

LR_PLAN_SCHEMA_VERSION=1
LR_HARNESSES="claude-code codex pi kiro"
# FR-9's tuning keys, with auto_compact_window (a launch-first binding key,
# departure 8; spec amendment of 2026-11-23).
LR_TUNING_KEYS="small_fast_model max_output_tokens reasoning_effort thinking auto_compact_window"

_lr_sha256() {
    { command -v shasum >/dev/null 2>&1 && shasum -a 256 || sha256sum; } | cut -d' ' -f1
}

_lr_value_json() {  # <ctx> <key> -> the value as JSON, typed as the file wrote it
    local type
    type=$(lc_type "$1" "$2") || { printf 'null'; return 0; }
    case "$type" in
        array) lc_array_elems "$1" "$2" | jq -R . | jq -sc . ;;
        int|bool) lc_get "$1" "$2" ;;
        *) jq -nc --arg v "$(lc_get "$1" "$2")" '$v' ;;
    esac
}

_lr_table_json() {  # <ctx> -> the table as a JSON object, keys sorted
    local key out='{}'
    while IFS= read -r key; do
        [[ -z "$key" ]] && continue
        out=$(jq -c --arg k "$key" --argjson v "$(_lr_value_json "$1" "$key")" '. + {($k): $v}' <<< "$out")
    done <<< "$(lc_keys "$1")"
    jq -cS . <<< "$out"
}

_lr_identity() {  # <binding-id>: what the plan names, without a digest
    local b="bindings.$1" l e url=""
    l=$(lc_get "$b" llm) || l=""
    LR_PROVIDER=$(lc_get "llms.$l" provider) || LR_PROVIDER=""
    LR_PROVIDER_KIND=$(lc_get "providers.$LR_PROVIDER" kind) || LR_PROVIDER_KIND=""
    LR_MODEL=$(lc_get "llms.$l" model) || LR_MODEL=""
    if e=$(lc_get "$b" endpoint); then
        LR_ENDPOINT_ID="$e"
        LR_PROTOCOL=$(lc_get "endpoints.$e" protocol) || LR_PROTOCOL=""
        if lc_endpoint_url "$e"; then url="$LC_URL"; fi
    fi
    if [[ -n "$url" ]]; then LR_ORIGIN=$(rt_sanitize_origin "$url"); fi
    return 0
}

# lr_digests: the three digests of the binding the last lr_resolve
# resolved, in LR_DIGEST_CATALOG, LR_DIGEST_LAUNCH and LR_DIGEST_OPTIONS.
# Returns 1 when that lr_resolve resolved no binding.
lr_digests() {
    [[ -n "$LR_BINDING" ]] || return 1
    local b="bindings.$LR_BINDING" l e="$LR_ENDPOINT_ID" ep="" url="" header="" mode="" cred="" quirks='[]'
    local endpoint_json='null' endpoint_provider_json='null' tuning='{}' key
    l=$(lc_get "$b" llm) || l=""
    if [[ -n "$e" ]]; then
        ep=$(lc_get "endpoints.$e" provider) || ep=""
        endpoint_json=$(jq -nc --arg id "$e" --argjson t "$(_lr_table_json "endpoints.$e")" '{id: $id, table: $t}')
        endpoint_provider_json=$(jq -nc --arg id "$ep" --argjson t "$(_lr_table_json "providers.$ep")" '{id: $id, table: $t}')
        header=$(lc_get "endpoints.$e" auth_header) || header=""
        mode=$(lc_get "providers.$ep" credential_mode) || mode=""
        cred=$(lc_get "providers.$ep" credential_env) || cred=""
        if lc_endpoint_url "$e"; then url="$LC_URL"; fi
        quirks=$(lc_array_elems "endpoints.$e" quirks 2>/dev/null | sort -u | jq -R . | jq -sc .)
    else
        mode=$(lc_get "providers.$LR_PROVIDER" credential_mode) || mode=""
    fi
    LR_DIGEST_CATALOG=$(jq -ncS \
        --arg b "$LR_BINDING" --argjson bt "$(_lr_table_json "$b")" \
        --arg l "$l" --argjson lt "$(_lr_table_json "llms.$l")" \
        --arg p "$LR_PROVIDER" --argjson pt "$(_lr_table_json "providers.$LR_PROVIDER")" \
        --argjson endpoint "$endpoint_json" --argjson endpoint_provider "$endpoint_provider_json" \
        '{binding: {id: $b, table: $bt}, llm: {id: $l, table: $lt}, provider: {id: $p, table: $pt},
          endpoint: $endpoint, endpoint_provider: $endpoint_provider}' | _lr_sha256)
    LR_DIGEST_LAUNCH=$(jq -nc \
        --arg h "$LR_HARNESS" --arg kind "$LR_PROVIDER_KIND" --arg url "$url" --arg proto "$LR_PROTOCOL" \
        --arg header "$header" --arg mode "$mode" --arg cred "$cred" --arg model "$LR_MODEL" --argjson quirks "$quirks" \
        '[$h, $kind, $url, $proto, $header, $mode, $cred, $model, $quirks]' | _lr_sha256)
    for key in $LR_TUNING_KEYS; do
        if lc_type "$b" "$key" >/dev/null; then
            tuning=$(jq -c --arg k "$key" --argjson v "$(_lr_value_json "$b" "$key")" '. + {($k): $v}' <<< "$tuning")
        fi
    done
    LR_DIGEST_OPTIONS=$(jq -cS . <<< "$tuning" | _lr_sha256)
    return 0
}

# lr_resolve <harness> <target>
# Returns 0 when the target resolves to a binding (LR_STATE then says
# whether it launches) and 1 when it does not (LR_REFUSAL says why). Sets
# LR_HARNESS, LR_TARGET, LR_LLM, LR_BINDING, LR_STATE, LR_REASON,
# LR_REFUSAL, the identity (LR_PROVIDER, LR_PROVIDER_KIND, LR_MODEL,
# LR_ENDPOINT_ID, LR_PROTOCOL, LR_ORIGIN), and through the adapter its
# LLM_CC_* plan. It clears the digests; lr_digests computes them.
# Only claude-code has an adapter; every other harness is refused with
# "adapter not implemented" until its slice lands (FR-21 to FR-23).
lr_resolve() {
    LR_HARNESS="$1"
    LR_TARGET="$2"
    LR_LLM="" LR_BINDING="" LR_STATE="" LR_REASON="" LR_REFUSAL=""
    LR_DIGEST_CATALOG="" LR_DIGEST_LAUNCH="" LR_DIGEST_OPTIONS=""
    LR_PROVIDER="" LR_PROVIDER_KIND="" LR_MODEL="" LR_ENDPOINT_ID="" LR_PROTOCOL="" LR_ORIGIN=""
    case " $LR_HARNESSES " in
        *" $1 "*) ;;
        *) LR_REFUSAL="unknown harness '$1' (one of: ${LR_HARNESSES// /, })"; return 1 ;;
    esac
    if [[ "$1" != "$LLM_CC_HARNESS" ]]; then
        LR_REFUSAL="adapter not implemented: --llm for $1 arrives with its own slice of #400"
        return 1
    fi
    if ! lc_resolve "$1" "$2"; then
        LR_REFUSAL="$LC_R_ERR"
        return 1
    fi
    LR_LLM="$LC_R_LLM"
    LR_BINDING="$LC_R_BINDING"
    llm_cc_plan "$LR_BINDING"
    LR_STATE="$LLM_CC_STATE"
    LR_REASON="$LLM_CC_REASON"
    _lr_identity "$LR_BINDING"
    return 0
}

_lr_env_names_json() {  # the plan's variables, by NAME: set or not, and where a copied value comes from
    local rec name kind payload isset out='[]'
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        name="${rec%%"$CT_US"*}"; rec="${rec#*"$CT_US"}"
        kind="${rec%%"$CT_US"*}"; payload="${rec#*"$CT_US"}"
        if [[ "$kind" == "env" ]]; then
            isset=false
            if [[ "$payload" =~ $LC_ENV_NAME_RE && -n "${!payload:-}" ]]; then isset=true; fi
            out=$(jq -c --arg n "$name" --argjson s "$isset" --arg f "$payload" '. + [{name: $n, set: $s, from: $f}]' <<< "$out")
        else
            out=$(jq -c --arg n "$name" '. + [{name: $n, set: true}]' <<< "$out")
        fi
    done <<< "$LLM_CC_ASSIGN"
    printf '%s' "$out"
}

_lr_clear_json() {  # the names the launch removes, in order, each once
    printf '%s\n' $LLM_CC_CLEAR | awk 'NF && !seen[$0]++' | jq -R . | jq -sc .
}

# lr_plan_json: the plan of the last lr_resolve as canonical JSON. Names
# and non-secret identity only: never a value of any variable.
lr_plan_json() {
    if [[ -z "$LR_BINDING" ]]; then
        jq -nc --argjson v "$LR_PLAN_SCHEMA_VERSION" --arg h "$LR_HARNESS" --arg t "$LR_TARGET" --arg r "$LR_REFUSAL" \
            '{schema_version: $v, harness: $h, target: $t, llm: null, binding: null, refusal: {state: null, reason: $r}}'
        return 0
    fi
    local refusal='null'
    lr_digests
    if [[ "$LR_STATE" != "unverified" ]]; then
        refusal=$(jq -nc --arg s "$LR_STATE" --arg r "$LR_REASON" '{state: $s, reason: $r}')
    fi
    jq -nc \
        --argjson v "$LR_PLAN_SCHEMA_VERSION" --arg h "$LR_HARNESS" --arg t "$LR_TARGET" \
        --arg l "$LR_LLM" --arg b "$LR_BINDING" \
        --argjson env "$(_lr_env_names_json)" --argjson clear "$(_lr_clear_json)" \
        --arg p "$LR_PROVIDER" --arg kind "$LR_PROVIDER_KIND" --arg origin "$LR_ORIGIN" \
        --arg proto "$LR_PROTOCOL" --arg model "$LR_MODEL" \
        --arg state "$LR_STATE" --arg reason "$LR_REASON" \
        --arg dc "$LR_DIGEST_CATALOG" --arg dl "$LR_DIGEST_LAUNCH" --arg dopt "$LR_DIGEST_OPTIONS" \
        --argjson refusal "$refusal" \
        '{schema_version: $v, harness: $h, target: $t, llm: $l, binding: $b,
          executable: "claude", argv: [], env_names: $env, env_clear: $clear, overlay: [],
          identity: {harness: $h, llm: $l, binding: $b, provider: $p, provider_kind: $kind,
                     endpoint: (if $origin == "" then null else $origin end),
                     protocol: (if $proto == "" then null else $proto end), model: $model},
          compatibility: {state: $state, reason: (if $reason == "" then null else $reason end)},
          digests: {catalog: $dc, launch_identity: $dl, options: $dopt},
          refusal: $refusal}'
}
