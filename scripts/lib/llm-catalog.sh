#!/usr/bin/env bash
# llm-catalog.sh — the LLM catalog: named providers, endpoints, models
# and harness bindings a user configures once and selects per launch
# with --llm (#479, the launch-first slice of #400).
#
# The catalog is ${CCT_HOME:-~/.cct}/llms.toml. It accepts ONLY the
# constrained-TOML subset lexed by cct-toml.sh plus the tables and keys
# named here; anything else is REFUSED BY NAME, never approximated, and
# a key whose behaviour nothing implements yet is refused rather than
# accepted as inert configuration.
#   - one root key before any table: schema_version = 1 (REQUIRED)
#   - [providers.<id>], [endpoints.<id>], [llms.<id>], [bindings.<id>]
#
# Credentials are REFERENCES: credential_env and base_url_env carry
# environment-variable NAMES. Nothing in this file reads a credential's
# value; lc_endpoint_url reads a base-URL variable, which is not one.
#
# bash 3.2 compatible, safe under `set -e` and `set -u`: no associative
# arrays; the parsed form is a newline-list of ctx<US>key<US>type<US>value
# records, exactly the routing registry's.

_LC_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=cct-toml.sh
source "$_LC_LIB_DIR/cct-toml.sh"
# shellcheck source=cct-endpoint.sh
source "$_LC_LIB_DIR/cct-endpoint.sh"
# shellcheck source=cct-home.sh
source "$_LC_LIB_DIR/cct-home.sh"

LC_FILE_NAME="llms.toml"
LC_SCHEMA_VERSION=1
LC_ID_RE='^[A-Za-z0-9][A-Za-z0-9_-]*$'
LC_TABLE_RE='^(providers|endpoints|llms|bindings)\.[A-Za-z0-9][A-Za-z0-9_-]*$'
LC_ENV_NAME_RE='^[A-Z_][A-Z0-9_]*$'
LC_EFFORT_RE='^[a-z]+$'

# The vocabulary. Closed sets: a value outside one is a violation.
LC_PROVIDER_KINDS="api managed"
LC_PROTOCOLS="anthropic-messages openai-chat openai-responses"
LC_AUTH_HEADERS="none bearer x-api-key"
LC_QUIRKS="rejects-dynamic-tools"
LC_INPUTS="text image"
LC_HARNESSES="claude-code codex pi kiro"
# The harnesses whose launcher takes --llm today. A binding for another
# one is refused by name until its launcher exists.
LC_HARNESSES_BUILT="claude-code"

LC_PROVIDER_KEYS="display_name kind credential_mode credential_env"
LC_ENDPOINT_KEYS="provider protocol base_url base_url_env auth_header quirks"
LC_LLM_KEYS="provider model context_window reasoning input"
LC_BINDING_KEYS="harness llm endpoint"
LC_BINDING_KEYS_CLAUDE_CODE="small_fast_model max_output_tokens auto_compact_window reasoning_effort"
# Named in #400 for a later slice; refused until something consumes it.
LC_KEYS_NOT_BUILT="data_policy"

lc_catalog_path() {  # -> the catalog file (it may not exist)
    cct_home_path "$LC_FILE_NAME"
}

_lc_in() {  # <needle> <space-separated list>
    local x
    for x in $2; do [[ "$x" == "$1" ]] && return 0; done
    return 1
}

# ── parse ─────────────────────────────────────────────────────────────
# lc_parse <file>
# Sets LC_PARSED (records), LC_CTXS (declared tables, file order),
# LC_LINES (ctx<US>key<US>line; an empty key is the table header) and
# LC_ERRORS (newline list of named grammar violations, "line N: ...").
# Returns 1 when LC_ERRORS is non-empty. Parsing continues past errors
# so one run names them all.
lc_parse() {
    local file="$1"
    LC_PARSED=""
    LC_CTXS=""
    LC_LINES=""
    LC_ERRORS=""
    local ctx="" lineno=0 raw line key val t
    local seen_tables=$'\n' seen_keys=$'\n'

    while IFS= read -r raw || [[ -n "$raw" ]]; do
        lineno=$((lineno + 1))
        ct_trim "$raw"
        line="$CT_LINE"
        if [[ -z "$line" || "${line:0:1}" == "#" ]]; then continue; fi

        # table headers
        if [[ "$line" =~ ^\[\[ ]]; then
            LC_ERRORS="${LC_ERRORS}line $lineno: array-of-tables is not accepted: '$line'"$'\n'
            ctx="__invalid__"; continue
        fi
        if [[ "$line" =~ ^\[([^]]*)\]$ ]]; then
            t="${BASH_REMATCH[1]}"
            if [[ "$t" =~ $LC_TABLE_RE ]]; then
                if [[ "$seen_tables" == *$'\n'"$t"$'\n'* ]]; then
                    LC_ERRORS="${LC_ERRORS}line $lineno: duplicate table declaration: [$t]"$'\n'
                    ctx="__invalid__"; continue
                fi
                seen_tables="${seen_tables}${t}"$'\n'
                LC_CTXS="${LC_CTXS}${t}"$'\n'
                LC_LINES="${LC_LINES}${t}${CT_US}${CT_US}${lineno}"$'\n'
                ctx="$t"; continue
            fi
            LC_ERRORS="${LC_ERRORS}line $lineno: table [$t] is not accepted (only [providers.<id>], [endpoints.<id>], [llms.<id>], [bindings.<id>]; an id is letters, digits, '_' and '-', starting with a letter or digit)"$'\n'
            ctx="__invalid__"; continue
        fi
        if [[ "${line:0:1}" == "[" ]]; then
            LC_ERRORS="${LC_ERRORS}line $lineno: malformed table header: '$line'"$'\n'
            ctx="__invalid__"; continue
        fi

        # key = value
        if ! ct_split_kv "$line"; then
            LC_ERRORS="${LC_ERRORS}line $lineno: $CT_ERR"$'\n'
            continue
        fi
        key="$CT_KEY"
        val="$CT_VAL"
        if [[ "$ctx" == "__invalid__" ]]; then continue; fi
        if [[ -z "$ctx" ]]; then
            # root: exactly schema_version
            if [[ "$key" != "schema_version" ]]; then
                LC_ERRORS="${LC_ERRORS}line $lineno: key '$key' appears outside any table (only schema_version may precede the first table)"$'\n'
                continue
            fi
            if [[ "$seen_keys" == *$'\n'"root${CT_US}schema_version"$'\n'* ]]; then
                LC_ERRORS="${LC_ERRORS}line $lineno: duplicate key 'schema_version'"$'\n'
                continue
            fi
            seen_keys="${seen_keys}root${CT_US}schema_version"$'\n'
            if [[ "$val" =~ ^[0-9]+$ ]]; then
                LC_PARSED="${LC_PARSED}root${CT_US}schema_version${CT_US}int${CT_US}${val}"$'\n'
                LC_LINES="${LC_LINES}root${CT_US}schema_version${CT_US}${lineno}"$'\n'
            else
                LC_ERRORS="${LC_ERRORS}line $lineno: schema_version must be an integer"$'\n'
            fi
            continue
        fi
        if [[ "$seen_keys" == *$'\n'"${ctx}${CT_US}${key}"$'\n'* ]]; then
            LC_ERRORS="${LC_ERRORS}line $lineno: duplicate key '$key' in [$ctx]"$'\n'
            continue
        fi
        seen_keys="${seen_keys}${ctx}${CT_US}${key}"$'\n'
        LC_LINES="${LC_LINES}${ctx}${CT_US}${key}${CT_US}${lineno}"$'\n'

        if ! ct_lex_value "$val"; then
            LC_ERRORS="${LC_ERRORS}line $lineno: $CT_ERR"$'\n'
            continue
        fi
        LC_PARSED="${LC_PARSED}${ctx}${CT_US}${key}${CT_US}${CT_TYPE}${CT_US}${CT_VALUE}"$'\n'
    done < "$file"

    [[ -z "$LC_ERRORS" ]]
}

# ── accessors over the parsed form ───────────────────────────────────
lc_get() {  # <ctx> <key> -> value (rc 1 when absent)
    local rec c rest k rest2
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        c="${rec%%"$CT_US"*}"; rest="${rec#*"$CT_US"}"
        k="${rest%%"$CT_US"*}"; rest2="${rest#*"$CT_US"}"
        if [[ "$c" == "$1" && "$k" == "$2" ]]; then
            printf '%s' "${rest2#*"$CT_US"}"
            return 0
        fi
    done <<< "$LC_PARSED"
    return 1
}

lc_type() {  # <ctx> <key> -> type (rc 1 when absent)
    local rec c rest k rest2
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        c="${rec%%"$CT_US"*}"; rest="${rec#*"$CT_US"}"
        k="${rest%%"$CT_US"*}"; rest2="${rest#*"$CT_US"}"
        if [[ "$c" == "$1" && "$k" == "$2" ]]; then
            printf '%s' "${rest2%%"$CT_US"*}"
            return 0
        fi
    done <<< "$LC_PARSED"
    return 1
}

lc_keys() {  # <ctx> -> newline list of the keys it sets
    local rec c rest
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        c="${rec%%"$CT_US"*}"; rest="${rec#*"$CT_US"}"
        if [[ "$c" == "$1" ]]; then printf '%s\n' "${rest%%"$CT_US"*}"; fi
    done <<< "$LC_PARSED"
    return 0
}

lc_has() {  # <ctx> -> 0 when the table is declared
    [[ $'\n'"$LC_CTXS" == *$'\n'"$1"$'\n'* ]]
}

lc_ids() {  # <table> -> newline list of its ids, file order
    local ctx
    while IFS= read -r ctx; do
        if [[ "$ctx" == "$1".* ]]; then printf '%s\n' "${ctx#"$1".}"; fi
    done <<< "$LC_CTXS"
    return 0
}

lc_array_elems() {  # <ctx> <key> -> newline list of array elements
    local v
    v=$(lc_get "$1" "$2") || return 1
    [[ -z "$v" ]] && return 0
    printf '%s\n' "$v" | tr "$CT_RS" '\n'
}

lc_line() {  # <ctx> <key, or empty for the table header> -> line number
    local rec c rest k
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        c="${rec%%"$CT_US"*}"; rest="${rec#*"$CT_US"}"
        k="${rest%%"$CT_US"*}"
        if [[ "$c" == "$1" && "$k" == "$2" ]]; then
            printf '%s' "${rest#*"$CT_US"}"
            return 0
        fi
    done <<< "$LC_LINES"
    return 1
}

# ── validate ─────────────────────────────────────────────────────────
# lc_validate <file>
# Prints one named violation per line, grammar first, then semantic,
# each "line N: ...". Returns 0 valid, 1 violations, 2 unreadable file.
# Leaves the parsed form in place for the caller.
lc_validate() {
    local file="$1" line ctx sv
    LC_VIOLATIONS=0
    if [[ ! -f "$file" || ! -r "$file" ]]; then
        printf 'cannot read the LLM catalog: %s\n' "$file"
        return 2
    fi
    lc_parse "$file" || true
    while IFS= read -r line; do
        if [[ -n "$line" ]]; then
            printf '%s\n' "$line"
            LC_VIOLATIONS=$((LC_VIOLATIONS + 1))
        fi
    done <<< "$LC_ERRORS"

    if sv=$(lc_get root schema_version); then
        if [[ "$sv" != "$LC_SCHEMA_VERSION" ]]; then
            printf 'line %s: schema_version %s is not supported (this version reads %s)\n' \
                "$(lc_line root schema_version || printf '?')" "$sv" "$LC_SCHEMA_VERSION"
            LC_VIOLATIONS=$((LC_VIOLATIONS + 1))
        fi
    elif [[ "$LC_ERRORS" != *"schema_version"* ]]; then
        printf 'line 1: schema_version = %s is required before the first table\n' "$LC_SCHEMA_VERSION"
        LC_VIOLATIONS=$((LC_VIOLATIONS + 1))
    fi

    while IFS= read -r ctx; do
        [[ -z "$ctx" ]] && continue
        case "$ctx" in
            providers.*) _lc_check_provider "$ctx" ;;
            endpoints.*) _lc_check_endpoint "$ctx" ;;
            llms.*)      _lc_check_llm "$ctx" ;;
            bindings.*)  _lc_check_binding "$ctx" ;;
        esac
        _lc_check_secrets "$ctx"
    done <<< "$LC_CTXS"
    _lc_check_duplicate_bindings

    [[ "$LC_VIOLATIONS" -eq 0 ]]
}

# A refused value is quoted back so the user can find it, unless it is
# shaped like a credential: that is never printed.
_lc_q() {  # <value>
    if ct_secretish "$1"; then printf '<redacted>'; else printf '%s' "$1"; fi
}

_lc_v() {  # <ctx> <key, or empty for the table> <message>
    local ln
    ln=$(lc_line "$1" "$2") || ln=$(lc_line "$1" "") || ln="?"
    printf 'line %s: [%s] %s\n' "$ln" "$1" "$3"
    LC_VIOLATIONS=$((LC_VIOLATIONS + 1))
    return 0
}

# _lc_typed <ctx> <key> <type>
# 0 present and of that type; 1 absent; 2 present with another type
# (reported).
_lc_typed() {
    local t want
    t=$(lc_type "$1" "$2") || return 1
    [[ "$t" == "$3" ]] && return 0
    case "$3" in
        string) want="a string" ;;
        int)    want="an integer" ;;
        bool)   want="true or false" ;;
        *)      want="an array of strings" ;;
    esac
    _lc_v "$1" "$2" "'$2' must be $want"
    return 2
}

_lc_closed_keys() {  # <ctx> <accepted keys>
    local k
    while IFS= read -r k; do
        [[ -z "$k" ]] && continue
        _lc_in "$k" "$2" && continue
        if _lc_in "$k" "$LC_KEYS_NOT_BUILT"; then
            _lc_v "$1" "$k" "'$k' is not implemented in this version"
        else
            _lc_v "$1" "$k" "unknown key '$k' (accepted: ${2// /, })"
        fi
    done <<< "$(lc_keys "$1")"
    return 0
}

_lc_positive_int() {  # <ctx> <key>
    local rc=0 v
    _lc_typed "$1" "$2" int || rc=$?
    if [[ $rc -eq 0 ]]; then
        v=$(lc_get "$1" "$2") || v=""
        if [[ ! "$v" =~ ^[1-9][0-9]*$ ]]; then _lc_v "$1" "$2" "'$2' must be a positive integer"; fi
    fi
    return 0
}

_lc_check_provider() {
    local ctx="$1" kind="" mode="" v rc
    _lc_closed_keys "$ctx" "$LC_PROVIDER_KEYS"
    _lc_typed "$ctx" display_name string || true

    rc=0; _lc_typed "$ctx" kind string || rc=$?
    if [[ $rc -eq 1 ]]; then
        _lc_v "$ctx" "" "kind is required (api | managed)"
    elif [[ $rc -eq 0 ]]; then
        kind=$(lc_get "$ctx" kind) || kind=""
        if ! _lc_in "$kind" "$LC_PROVIDER_KINDS"; then
            _lc_v "$ctx" kind "kind '$(_lc_q "$kind")' is not accepted (api | managed)"
            kind=""
        fi
    fi

    rc=0; _lc_typed "$ctx" credential_mode string || rc=$?
    if [[ $rc -eq 1 ]]; then
        _lc_v "$ctx" "" "credential_mode is required (env | none for an api provider, native for a managed one)"
    elif [[ $rc -eq 0 ]]; then
        mode=$(lc_get "$ctx" credential_mode) || mode=""
        case "$mode" in
            keychain)
                _lc_v "$ctx" credential_mode "secure-store credentials are not implemented"
                mode="" ;;
            env|none)
                if [[ "$kind" == "managed" ]]; then
                    _lc_v "$ctx" credential_mode "credential_mode '$mode' is not accepted for a managed provider (native only: the harness signs in itself)"
                fi ;;
            native)
                if [[ "$kind" == "api" ]]; then
                    _lc_v "$ctx" credential_mode "credential_mode 'native' is not accepted for an api provider (a harness's own login is never sent to a custom endpoint)"
                fi ;;
            *)
                _lc_v "$ctx" credential_mode "credential_mode '$(_lc_q "$mode")' is not accepted (env | none | native)"
                mode="" ;;
        esac
    fi

    rc=0; _lc_typed "$ctx" credential_env string || rc=$?
    if [[ $rc -eq 0 ]]; then
        v=$(lc_get "$ctx" credential_env) || v=""
        if [[ -n "$mode" && "$mode" != "env" ]]; then
            _lc_v "$ctx" credential_env "credential_env is only accepted with credential_mode = \"env\""
        elif [[ ! "$v" =~ $LC_ENV_NAME_RE ]]; then
            _lc_v "$ctx" credential_env "credential_env must be an environment-variable NAME ([A-Z_][A-Z0-9_]*), never a value"
        fi
    elif [[ $rc -eq 1 && "$mode" == "env" ]]; then
        _lc_v "$ctx" credential_mode "credential_env is required with credential_mode = \"env\" (the NAME of the variable that holds the credential)"
    fi
    return 0
}

_lc_check_endpoint() {
    local ctx="$1" p="" pmode="" v rc has_url=0 has_env=0 header="" why q
    _lc_closed_keys "$ctx" "$LC_ENDPOINT_KEYS"

    rc=0; _lc_typed "$ctx" provider string || rc=$?
    if [[ $rc -eq 1 ]]; then
        _lc_v "$ctx" "" "provider is required"
    elif [[ $rc -eq 0 ]]; then
        p=$(lc_get "$ctx" provider) || p=""
        if ! lc_has "providers.$p"; then
            _lc_v "$ctx" provider "provider '$(_lc_q "$p")' is not defined"
        else
            pmode=$(lc_get "providers.$p" credential_mode) || pmode=""
            v=$(lc_get "providers.$p" kind) || v=""
            if [[ "$v" == "managed" ]]; then
                _lc_v "$ctx" provider "an endpoint cannot belong to a managed provider ('$p' is reached by the harness's own login)"
            fi
        fi
    fi

    rc=0; _lc_typed "$ctx" protocol string || rc=$?
    if [[ $rc -eq 1 ]]; then
        _lc_v "$ctx" "" "protocol is required (${LC_PROTOCOLS// / | })"
    elif [[ $rc -eq 0 ]]; then
        v=$(lc_get "$ctx" protocol) || v=""
        if ! _lc_in "$v" "$LC_PROTOCOLS"; then
            _lc_v "$ctx" protocol "protocol '$(_lc_q "$v")' is not accepted (${LC_PROTOCOLS// / | })"
        fi
    fi

    rc=0; _lc_typed "$ctx" base_url string || rc=$?
    if [[ $rc -ne 1 ]]; then has_url=1; fi
    if [[ $rc -eq 0 ]]; then
        v=$(lc_get "$ctx" base_url) || v=""
        why=$(ce_url_violation "$v")
        if [[ -n "$why" ]]; then _lc_v "$ctx" base_url "base_url $why"; fi
    fi
    rc=0; _lc_typed "$ctx" base_url_env string || rc=$?
    if [[ $rc -ne 1 ]]; then has_env=1; fi
    if [[ $rc -eq 0 ]]; then
        v=$(lc_get "$ctx" base_url_env) || v=""
        if [[ ! "$v" =~ $LC_ENV_NAME_RE ]]; then
            _lc_v "$ctx" base_url_env "base_url_env must be an environment-variable NAME ([A-Z_][A-Z0-9_]*)"
        fi
    fi
    if [[ $((has_url + has_env)) -ne 1 ]]; then
        _lc_v "$ctx" "" "exactly one of base_url | base_url_env is required"
    fi

    rc=0; _lc_typed "$ctx" auth_header string || rc=$?
    if [[ $rc -eq 1 ]]; then
        _lc_v "$ctx" "" "auth_header is required (${LC_AUTH_HEADERS// / | })"
    elif [[ $rc -eq 0 ]]; then
        header=$(lc_get "$ctx" auth_header) || header=""
        if ! _lc_in "$header" "$LC_AUTH_HEADERS"; then
            _lc_v "$ctx" auth_header "auth_header '$(_lc_q "$header")' is not accepted (${LC_AUTH_HEADERS// / | })"
        elif [[ "$pmode" == "none" && "$header" != "none" ]]; then
            _lc_v "$ctx" auth_header "auth_header must be \"none\": provider '$p' has credential_mode = \"none\""
        elif [[ "$pmode" == "env" && "$header" == "none" ]]; then
            _lc_v "$ctx" auth_header "auth_header \"none\" is not accepted: provider '$p' has a credential (bearer | x-api-key)"
        fi
    fi

    rc=0; _lc_typed "$ctx" quirks array || rc=$?
    if [[ $rc -eq 0 ]]; then
        while IFS= read -r q; do
            [[ -z "$q" ]] && continue
            if ! _lc_in "$q" "$LC_QUIRKS"; then
                _lc_v "$ctx" quirks "quirk '$(_lc_q "$q")' is not accepted (${LC_QUIRKS// / | })"
            fi
        done <<< "$(lc_array_elems "$ctx" quirks)"
    fi
    return 0
}

_lc_check_llm() {
    local ctx="$1" v rc i
    _lc_closed_keys "$ctx" "$LC_LLM_KEYS"

    rc=0; _lc_typed "$ctx" provider string || rc=$?
    if [[ $rc -eq 1 ]]; then
        _lc_v "$ctx" "" "provider is required"
    elif [[ $rc -eq 0 ]]; then
        v=$(lc_get "$ctx" provider) || v=""
        if ! lc_has "providers.$v"; then
            _lc_v "$ctx" provider "provider '$(_lc_q "$v")' is not defined"
        fi
    fi

    rc=0; _lc_typed "$ctx" model string || rc=$?
    if [[ $rc -eq 1 ]]; then
        _lc_v "$ctx" "" "model is required (the model id the provider expects)"
    elif [[ $rc -eq 0 ]]; then
        v=$(lc_get "$ctx" model) || v=""
        if [[ -z "$v" || "$v" =~ [[:space:]] ]]; then
            _lc_v "$ctx" model "model must be a non-empty id without whitespace"
        fi
    fi

    _lc_positive_int "$ctx" context_window
    _lc_typed "$ctx" reasoning bool || true
    rc=0; _lc_typed "$ctx" input array || rc=$?
    if [[ $rc -eq 0 ]]; then
        while IFS= read -r i; do
            [[ -z "$i" ]] && continue
            if ! _lc_in "$i" "$LC_INPUTS"; then
                _lc_v "$ctx" input "input '$(_lc_q "$i")' is not accepted (${LC_INPUTS// / | })"
            fi
        done <<< "$(lc_array_elems "$ctx" input)"
    fi
    return 0
}

_lc_check_binding() {
    local ctx="$1" h="" l="" e lp="" lkind="" v rc
    rc=0; _lc_typed "$ctx" harness string || rc=$?
    if [[ $rc -eq 1 ]]; then
        _lc_v "$ctx" "" "harness is required (${LC_HARNESSES// / | })"
    elif [[ $rc -eq 0 ]]; then
        h=$(lc_get "$ctx" harness) || h=""
        if ! _lc_in "$h" "$LC_HARNESSES"; then
            _lc_v "$ctx" harness "harness '$(_lc_q "$h")' is not accepted (${LC_HARNESSES// / | })"
            h=""
        elif ! _lc_in "$h" "$LC_HARNESSES_BUILT"; then
            _lc_v "$ctx" harness "harness '$h' has no --llm launcher in this version (${LC_HARNESSES_BUILT// /, } only)"
            h=""
        fi
    fi
    # A binding's own keys are checked only for a harness that has a
    # launcher; the refusal above already covers the others.
    if [[ "$h" == "claude-code" ]]; then
        _lc_closed_keys "$ctx" "$LC_BINDING_KEYS $LC_BINDING_KEYS_CLAUDE_CODE"
    fi

    rc=0; _lc_typed "$ctx" llm string || rc=$?
    if [[ $rc -eq 1 ]]; then
        _lc_v "$ctx" "" "llm is required"
    elif [[ $rc -eq 0 ]]; then
        l=$(lc_get "$ctx" llm) || l=""
        if ! lc_has "llms.$l"; then
            _lc_v "$ctx" llm "llm '$(_lc_q "$l")' is not defined"
        else
            lp=$(lc_get "llms.$l" provider) || lp=""
            lkind=$(lc_get "providers.$lp" kind) || lkind=""
        fi
    fi

    rc=0; _lc_typed "$ctx" endpoint string || rc=$?
    if [[ $rc -eq 0 ]]; then
        e=$(lc_get "$ctx" endpoint) || e=""
        if [[ "$lkind" == "managed" ]]; then
            _lc_v "$ctx" endpoint "a binding to a managed provider's llm cannot name an endpoint ('$lp' is reached by the harness's own login)"
        elif ! lc_has "endpoints.$e"; then
            _lc_v "$ctx" endpoint "endpoint '$(_lc_q "$e")' is not defined"
        fi
    elif [[ $rc -eq 1 && "$lkind" == "api" ]]; then
        _lc_v "$ctx" "" "endpoint is required: llm '$l' belongs to the api provider '$lp'"
    fi

    if [[ "$h" == "claude-code" ]]; then
        rc=0; _lc_typed "$ctx" small_fast_model string || rc=$?
        if [[ $rc -eq 0 ]]; then
            v=$(lc_get "$ctx" small_fast_model) || v=""
            if [[ "$lkind" == "managed" ]]; then
                _lc_v "$ctx" small_fast_model "small_fast_model applies to an endpoint binding; a managed provider keeps its own model aliases"
            elif [[ -z "$v" || "$v" =~ [[:space:]] ]]; then
                _lc_v "$ctx" small_fast_model "small_fast_model must be a non-empty id without whitespace"
            fi
        fi
        _lc_positive_int "$ctx" max_output_tokens
        _lc_positive_int "$ctx" auto_compact_window
        rc=0; _lc_typed "$ctx" reasoning_effort string || rc=$?
        if [[ $rc -eq 0 ]]; then
            v=$(lc_get "$ctx" reasoning_effort) || v=""
            if [[ ! "$v" =~ $LC_EFFORT_RE ]]; then
                _lc_v "$ctx" reasoning_effort "reasoning_effort must be one lowercase word (for example \"high\")"
            fi
        fi
    fi
    return 0
}

_lc_check_secrets() {  # <ctx>: no value may look like a credential
    local ctx="$1" k v e
    while IFS= read -r k; do
        [[ -z "$k" ]] && continue
        v=$(lc_get "$ctx" "$k") || v=""
        while IFS= read -r e; do
            [[ -z "$e" ]] && continue
            if ct_secretish "$e"; then
                _lc_v "$ctx" "$k" "'$k' holds a value that looks like a credential; the catalog names the environment variable that holds it (credential_env), never the value"
                break
            fi
        done <<< "$(printf '%s' "$v" | tr "$CT_RS" '\n')"
    done <<< "$(lc_keys "$ctx")"
    return 0
}

_lc_check_duplicate_bindings() {
    local ctx seen=$'\n' tuple first rec
    while IFS= read -r ctx; do
        case "$ctx" in bindings.*) ;; *) continue ;; esac
        tuple="$(lc_get "$ctx" harness || true)${CT_US}$(lc_get "$ctx" llm || true)${CT_US}$(lc_get "$ctx" endpoint || true)"
        first=""
        while IFS= read -r rec; do
            if [[ -n "$rec" && "${rec#*"$CT_RS"}" == "$tuple" ]]; then first="${rec%%"$CT_RS"*}"; break; fi
        done <<< "$seen"
        if [[ -n "$first" ]]; then
            _lc_v "$ctx" "" "duplicates [$first]: one binding per (harness, llm, endpoint)"
        else
            seen="${seen}${ctx}${CT_RS}${tuple}"$'\n'
        fi
    done <<< "$LC_CTXS"
    return 0
}

# ── resolution ───────────────────────────────────────────────────────
# lc_resolve <harness> <target>
# A target is <llm> or <llm>@<binding>. <llm> resolves through the ONE
# explicit binding for (harness, llm); several need the @<binding> form
# and none is refused. No binding is ever inferred. Sets LC_R_LLM and
# LC_R_BINDING; returns 1 with LC_R_ERR set.
lc_resolve() {
    local harness="$1" target="$2" l b="" ctx h bl matches="" n=0
    LC_R_LLM=""
    LC_R_BINDING=""
    LC_R_ERR=""
    l="$target"
    if [[ "$target" == *@* ]]; then
        l="${target%%@*}"
        b="${target#*@}"
        if [[ ! "$b" =~ $LC_ID_RE ]]; then
            LC_R_ERR="'$target' is not a target (<llm> or <llm>@<binding>)"
            return 1
        fi
    fi
    if [[ ! "$l" =~ $LC_ID_RE ]]; then
        LC_R_ERR="'$target' is not a target (<llm> or <llm>@<binding>)"
        return 1
    fi
    if ! lc_has "llms.$l"; then
        LC_R_ERR="unknown llm '$l' (cct llm list shows the catalog)"
        return 1
    fi
    if [[ -n "$b" ]]; then
        if ! lc_has "bindings.$b"; then
            LC_R_ERR="unknown binding '$b' (cct llm list shows the catalog)"
            return 1
        fi
        h=$(lc_get "bindings.$b" harness) || h=""
        bl=$(lc_get "bindings.$b" llm) || bl=""
        if [[ "$bl" != "$l" ]]; then
            LC_R_ERR="binding '$b' is for llm '$bl', not '$l'"
            return 1
        fi
        if [[ "$h" != "$harness" ]]; then
            LC_R_ERR="binding '$b' is for $h, not $harness"
            return 1
        fi
        LC_R_LLM="$l"
        LC_R_BINDING="$b"
        return 0
    fi
    while IFS= read -r ctx; do
        case "$ctx" in bindings.*) ;; *) continue ;; esac
        h=$(lc_get "$ctx" harness) || h=""
        bl=$(lc_get "$ctx" llm) || bl=""
        if [[ "$h" == "$harness" && "$bl" == "$l" ]]; then
            matches="${matches}${ctx#bindings.} "
            n=$((n + 1))
        fi
    done <<< "$LC_CTXS"
    matches="${matches% }"
    if [[ $n -eq 0 ]]; then
        LC_R_ERR="llm '$l' has no binding for $harness: add a [bindings.<id>] table with harness = \"$harness\" and llm = \"$l\""
        return 1
    fi
    if [[ $n -gt 1 ]]; then
        LC_R_ERR="llm '$l' has several bindings for $harness (${matches// /, }): use --llm $l@<binding>"
        return 1
    fi
    LC_R_LLM="$l"
    LC_R_BINDING="$matches"
    return 0
}

# lc_endpoint_url <endpoint-id>
# Resolves the endpoint's base URL into LC_URL: the literal base_url, or
# the value of the variable base_url_env names (configuration, not a
# credential), checked by the same rule every time it is read. Returns 1
# with LC_URL_ERR set when the variable is unset or its value is refused.
lc_endpoint_url() {
    local ctx="endpoints.$1" name why
    LC_URL=""
    LC_URL_ERR=""
    if LC_URL=$(lc_get "$ctx" base_url); then return 0; fi
    name=$(lc_get "$ctx" base_url_env) || name=""
    # The name is checked HERE as well as by the validator: it is about
    # to be used in an indirect expansion, which evaluates a subscript.
    if [[ ! "$name" =~ $LC_ENV_NAME_RE ]]; then
        LC_URL_ERR="endpoint '$1' has no usable base URL"
        return 1
    fi
    LC_URL="${!name:-}"
    if [[ -z "$LC_URL" ]]; then
        LC_URL_ERR="base URL variable $name is not set"
        return 1
    fi
    why=$(ce_url_violation "$LC_URL")
    if [[ -n "$why" ]]; then
        LC_URL=""
        LC_URL_ERR="the value of $name $why"
        return 1
    fi
    return 0
}

# ── a project's restriction (#400 FR-24, D13, slice S5) ──────────────
LC_PROJECT_CONFIG=".cct.toml"   # the committed project file (#460); never .cct.local.toml or the legacy one
LC_POLICY_TABLE="llm"
# The table's name as TOML may write it: bare, or quoted either way.
LC_POLICY_TABLE_RE="($LC_POLICY_TABLE|\"$LC_POLICY_TABLE\"|'$LC_POLICY_TABLE')"
LC_POLICY_KEY="allowed"
LC_TARGET_RE='^[A-Za-z0-9][A-Za-z0-9_-]*(@[A-Za-z0-9][A-Za-z0-9_-]*)?$'

# lc_project_policy <project-root>
# The [llm] table of <project-root>/.cct.toml, and nothing else of the
# file, which is Pi's configuration first: a table this lexer does not
# accept elsewhere in it can never block a launch. Sets LC_POLICY_FILE
# (empty: the project restricts nothing) and LC_ALLOWED (the allowed llm
# ids and <llm>@<binding> targets, one per line; empty with a policy file
# means none). Returns 1 with LC_POLICY_ERR when [llm] holds anything but
# `allowed = [...]`, in any form: projects restrict, never grant; and when
# the file cannot be read, or the project directory cannot be searched for
# it, since a restriction that cannot be read is never read as none.
lc_project_policy() {
    local file="$1/$LC_PROJECT_CONFIG" raw line lineno=0 in=0 root=1 seen=0 e
    LC_POLICY_FILE="" LC_ALLOWED="" LC_POLICY_ERR=""
    if [[ -d "$1" && ! -x "$1" ]]; then
        LC_POLICY_ERR="cannot read $file: the directory cannot be searched"
        return 1
    fi
    [[ -e "$file" || -L "$file" ]] || return 0
    if [[ ! -f "$file" || ! -r "$file" ]]; then
        LC_POLICY_ERR="cannot read $file"
        return 1
    fi
    while IFS= read -r raw || [[ -n "$raw" ]]; do
        lineno=$((lineno + 1))
        [[ "$lineno" -eq 1 ]] && raw="${raw#$'\xef\xbb\xbf'}"   # a UTF-8 byte-order mark
        ct_trim "$raw"
        line="$CT_LINE"
        if [[ -z "$line" || "${line:0:1}" == "#" ]]; then continue; fi
        if [[ "${line:0:1}" == "[" ]]; then
            in=0 root=0
            # The header may carry a comment, as TOML allows.
            if [[ "$line" =~ ^\[[[:space:]]*$LC_POLICY_TABLE_RE[[:space:]]*\][[:space:]]*(#.*)?$ ]]; then
                in=1
            elif [[ "$line" =~ ^\[\[?[[:space:]]*$LC_POLICY_TABLE_RE[[:space:]]*(\.|\]\]) ]]; then
                LC_POLICY_ERR="$file line $lineno: '$line' is not accepted: projects restrict, never grant (only [$LC_POLICY_TABLE] $LC_POLICY_KEY = [...])"
                return 1
            fi
            continue
        fi
        if [[ "$in" -eq 0 ]]; then
            # Another table's key is that table's own. At the root, `llm.allowed
            # = [...]` or `llm = {...}` would be the same table spelled
            # another way: refused, so it is never silently ignored.
            if [[ "$root" -eq 1 && "$line" =~ ^$LC_POLICY_TABLE_RE[[:space:]]*[.=] ]]; then
                LC_POLICY_ERR="$file line $lineno: write the project's LLM restriction as an [$LC_POLICY_TABLE] table with $LC_POLICY_KEY = [...]"
                return 1
            fi
            continue
        fi
        if ! ct_split_kv "$line"; then
            LC_POLICY_ERR="$file line $lineno: $CT_ERR"
            return 1
        fi
        if [[ "$CT_KEY" != "$LC_POLICY_KEY" ]]; then
            LC_POLICY_ERR="$file line $lineno: [$LC_POLICY_TABLE].$CT_KEY is not accepted: projects restrict, never grant (only $LC_POLICY_KEY = [...])"
            return 1
        fi
        if [[ "$seen" -eq 1 ]]; then
            LC_POLICY_ERR="$file line $lineno: [$LC_POLICY_TABLE].$LC_POLICY_KEY is given twice"
            return 1
        fi
        seen=1
        if ! ct_lex_value "$CT_VAL" || [[ "$CT_TYPE" != "array" ]]; then
            LC_POLICY_ERR="$file line $lineno: [$LC_POLICY_TABLE].$LC_POLICY_KEY must be an array of llm ids or <llm>@<binding> targets"
            return 1
        fi
        LC_POLICY_FILE="$file"
        if [[ -n "$CT_VALUE" ]]; then
            while IFS= read -r e; do
                if [[ ! "$e" =~ $LC_TARGET_RE ]]; then
                    LC_POLICY_ERR="$file line $lineno: '$e' in [$LC_POLICY_TABLE].$LC_POLICY_KEY is not an llm id or <llm>@<binding> target"
                    LC_POLICY_FILE=""
                    return 1
                fi
                LC_ALLOWED="${LC_ALLOWED}${e}"$'\n'
            done <<< "${CT_VALUE//$CT_RS/$'\n'}"
        fi
    done < "$file"
    return 0
}

# lc_policy_allows <llm> <binding>: 0 when no policy restricts, or the
# policy lists the llm or <llm>@<binding> (call lc_project_policy first).
lc_policy_allows() {
    [[ -z "$LC_POLICY_FILE" ]] && return 0
    printf '%s' "$LC_ALLOWED" | grep -qxF -e "$1" -e "$1@$2"
}

# lc_project_roots <dir>: the directories whose .cct.toml restricts a launch
# in <dir>, one per line: its git top level. When git names none, the
# directory itself and, when it or a directory above it holds .git, the
# nearest such directory too: git may be refusing a work tree there (a
# checkout it will not work in, a broken worktree pointer) or finding none
# on purpose (a ceiling directory). A project only restricts, so every
# root's list applies.
lc_project_roots() {
    local d top
    if top=$(git -C "$1" rev-parse --show-toplevel 2>/dev/null); then printf '%s\n' "$top"; return 0; fi
    d=$(cd "$1" 2>/dev/null && pwd -P) || { printf '%s\n' "$1"; return 0; }
    printf '%s\n' "$d"
    top="$d"
    while [[ ! -e "$top/.git" && "$top" != "/" ]]; do top=$(dirname "$top"); done
    if [[ -e "$top/.git" && "$top" != "$d" ]]; then printf '%s\n' "$top"; fi
}
