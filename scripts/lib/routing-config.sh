#!/usr/bin/env bash
# routing-config.sh — the execution-profile registry: constrained-TOML
# parser, vocabulary, and validator (#248, increment A of #109).
#
# routing.toml accepts ONLY the TOML subset implemented here; anything
# else is REJECTED BY NAME, never approximated (plan decision 1) — a
# closed schema over an approximating parser would not be closed, and
# this file is policy surface. Accepted grammar:
#   - comments (# ...) and blank lines
#   - one root key before any table: schema_version = 1 (REQUIRED)
#   - [policy], [route_classes.<name>], [[profiles]] table headers
#   - key = value with bare keys [A-Za-z0-9_-]+
#   - values: single-line basic strings ("...", the only escape is \"),
#     integers, booleans, single-line arrays of basic strings
# Rejected by name: duplicate keys in a table, duplicate table
# declarations, dotted keys, inline tables, multiline strings, literal
# (single-quoted) strings, non-string arrays, malformed quoting, any
# other array-of-tables, and any unrecognized line.
#
# The security boundary for credentials is STRUCTURAL (decision 3): no
# field can hold a literal credential — credential_env / base_url_env
# carry environment-variable NAMES and nothing here ever reads those
# variables' values. The secret-shape scan below is defense in depth
# against operator mistakes, not complete secret detection.
#
# bash 3.2 compatible: no associative arrays; parsed form is a
# newline-list of ctx<US>key<US>type<US>value records (US = \x1f;
# array elements joined with RS = \x1e).

RC_US=$'\x1f'
RC_RS=$'\x1e'

# The framework vocabulary (decision 2). Tiers are CLOSED semantic
# classes — operators configure profiles/priorities/pools, never the
# tier vocabulary itself.
RC_BACKENDS="claude-code codex pi"
RC_TIERS="tier1 tier2"
RC_ROLES="build reconcile land bounded-build"
RC_DATA_POLICIES="approved-cloud local-only"

# [policy] accepts ONLY what increment A consumes: `enabled` (gates the
# whole feature in the T4 merge and every command) and
# `preferred_profile` (declarative identity, rendered by status).
# Behavior-bearing keys whose enforcement arrives with B/D are REFUSED
# BY NAME, not accepted as inert configuration — a validated registry
# must never claim a behavior nothing enforces. When an increment
# implements one, its task moves that key from refused to accepted AND
# behaviorally tested (a crisp audit trail for when config becomes
# real).
RC_POLICY_KEYS="enabled preferred_profile"
RC_POLICY_FUTURE_KEYS="max_switches_per_task failback healthy_probes_required minimum_profile_dwell_sec"

RC_PROFILE_REQUIRED="id backend provider model capability_tier priority quota_pool roles tool_profile data_policy"
RC_PROFILE_OPTIONAL="credential_mode credential_env protocol base_url base_url_env"

# ── parse ─────────────────────────────────────────────────────────────
# rc_parse <file>
# Sets RC_PARSED (record list) and RC_ERRORS (newline list of named
# grammar violations, each "line N: ..."). Returns 1 when RC_ERRORS is
# non-empty. Parsing continues past errors so one run names them all.
rc_parse() {
    local file="$1"
    RC_PARSED=""
    RC_ERRORS=""
    RC_PROFILE_COUNT=0
    local ctx="" lineno=0 raw line key val
    local seen_tables=$'\n' seen_keys=$'\n'

    _rc_err() { RC_ERRORS="${RC_ERRORS}line $1: $2"$'\n'; }
    _rc_put() {  # ctx key type value
        RC_PARSED="${RC_PARSED}$1${RC_US}$2${RC_US}$3${RC_US}$4"$'\n'
    }

    while IFS= read -r raw || [[ -n "$raw" ]]; do
        lineno=$((lineno + 1))
        line="${raw#"${raw%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [[ -z "$line" || "${line:0:1}" == "#" ]] && continue

        # table headers
        if [[ "$line" == "[[profiles]]" ]]; then
            ctx="profiles.$RC_PROFILE_COUNT"
            RC_PROFILE_COUNT=$((RC_PROFILE_COUNT + 1))
            continue
        fi
        if [[ "$line" =~ ^\[\[ ]]; then
            _rc_err "$lineno" "array-of-tables other than [[profiles]] is not accepted: '$line'"
            ctx="__invalid__"; continue
        fi
        if [[ "$line" =~ ^\[([^]]*)\]$ ]]; then
            local t="${BASH_REMATCH[1]}"
            if [[ "$t" == "policy" || "$t" =~ ^route_classes\.[a-z0-9_]+$ ]]; then
                if [[ "$seen_tables" == *$'\n'"$t"$'\n'* ]]; then
                    _rc_err "$lineno" "duplicate table declaration: [$t]"
                    ctx="__invalid__"; continue
                fi
                seen_tables="${seen_tables}${t}"$'\n'
                ctx="$t"; continue
            fi
            _rc_err "$lineno" "table [$t] is not accepted (only [policy], [route_classes.<name>], [[profiles]])"
            ctx="__invalid__"; continue
        fi
        if [[ "${line:0:1}" == "[" ]]; then
            _rc_err "$lineno" "malformed table header: '$line'"
            ctx="__invalid__"; continue
        fi

        # key = value
        if [[ ! "$line" =~ ^([A-Za-z0-9_.-]+)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
            _rc_err "$lineno" "unrecognized line (not a comment, table header, or key = value): '$line'"
            continue
        fi
        key="${BASH_REMATCH[1]}"
        val="${BASH_REMATCH[2]}"
        if [[ "$key" == *.* ]]; then
            _rc_err "$lineno" "dotted keys are not accepted: '$key'"
            continue
        fi
        if [[ -z "$ctx" ]]; then
            if [[ "$key" == "schema_version" ]]; then
                ctx=""  # recorded under the root context below
            else
                _rc_err "$lineno" "key '$key' appears outside any table (only schema_version may precede the first table)"
                continue
            fi
        fi
        [[ "$ctx" == "__invalid__" ]] && continue
        if [[ -z "$ctx" ]]; then
            # root: exactly schema_version
            if [[ "$seen_keys" == *$'\n'"root${RC_US}schema_version"$'\n'* ]]; then
                _rc_err "$lineno" "duplicate key 'schema_version'"
                continue
            fi
            seen_keys="${seen_keys}root${RC_US}schema_version"$'\n'
            if [[ "$val" =~ ^[0-9]+$ ]]; then
                _rc_put "root" "schema_version" "int" "$val"
            else
                _rc_err "$lineno" "schema_version must be an integer"
            fi
            continue
        fi
        if [[ "$seen_keys" == *$'\n'"${ctx}${RC_US}${key}"$'\n'* ]]; then
            _rc_err "$lineno" "duplicate key '$key' in [$ctx]"
            continue
        fi
        seen_keys="${seen_keys}${ctx}${RC_US}${key}"$'\n'

        # value forms — reject the unsupported ones BY NAME first
        case "$val" in
            '"""'*) _rc_err "$lineno" "multiline strings are not accepted"; continue ;;
            "'"*)   _rc_err "$lineno" "literal (single-quoted) strings are not accepted"; continue ;;
            "{"*)   _rc_err "$lineno" "inline tables are not accepted"; continue ;;
        esac
        if [[ "$val" =~ ^\"([^\"\\]|\\\")*\"$ ]]; then
            local s="${val:1:${#val}-2}"
            s="${s//\\\"/\"}"
            _rc_put "$ctx" "$key" "string" "$s"
        elif [[ "$val" == "true" || "$val" == "false" ]]; then
            _rc_put "$ctx" "$key" "bool" "$val"
        elif [[ "$val" =~ ^-?[0-9]+$ ]]; then
            _rc_put "$ctx" "$key" "int" "$val"
        elif [[ "${val:0:1}" == "[" ]]; then
            if [[ ! "$val" =~ ^\[[[:space:]]*(\"([^\"\\]|\\\")*\"([[:space:]]*,[[:space:]]*\"([^\"\\]|\\\")*\")*[[:space:]]*)?\]$ ]]; then
                _rc_err "$lineno" "only single-line arrays of basic strings are accepted: '$val'"
                continue
            fi
            local inner="${val:1:${#val}-2}" elems="" e rest
            rest="$inner"
            while [[ "$rest" =~ ^[[:space:]]*\"(([^\"\\]|\\\")*)\"[[:space:]]*(,(.*))?$ ]]; do
                e="${BASH_REMATCH[1]}"; e="${e//\\\"/\"}"
                elems="${elems}${e}${RC_RS}"
                rest="${BASH_REMATCH[4]}"
                [[ -z "${BASH_REMATCH[3]}" ]] && rest=""
                [[ -z "$rest" ]] && break
            done
            _rc_put "$ctx" "$key" "array" "${elems%"$RC_RS"}"
        elif [[ "$val" == *'"'* ]]; then
            _rc_err "$lineno" "malformed quoting: '$val'"
            continue
        else
            _rc_err "$lineno" "unrecognized value form: '$val' (basic string, integer, boolean, or array of basic strings)"
            continue
        fi
    done < "$file"

    [[ -z "$RC_ERRORS" ]]
}

# ── accessors over RC_PARSED ─────────────────────────────────────────
rc_get() {  # <ctx> <key> -> value (empty + rc 1 when absent)
    local rec
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        local c="${rec%%"$RC_US"*}" rest="${rec#*"$RC_US"}"
        local k="${rest%%"$RC_US"*}" rest2="${rest#*"$RC_US"}"
        local v="${rest2#*"$RC_US"}"
        if [[ "$c" == "$1" && "$k" == "$2" ]]; then printf '%s' "$v"; return 0; fi
    done <<< "$RC_PARSED"
    return 1
}

rc_type() {  # <ctx> <key> -> type
    local rec
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        local c="${rec%%"$RC_US"*}" rest="${rec#*"$RC_US"}"
        local k="${rest%%"$RC_US"*}" rest2="${rest#*"$RC_US"}"
        local t="${rest2%%"$RC_US"*}"
        if [[ "$c" == "$1" && "$k" == "$2" ]]; then printf '%s' "$t"; return 0; fi
    done <<< "$RC_PARSED"
    return 1
}

rc_keys() {  # <ctx> -> newline list of keys
    local rec
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        local c="${rec%%"$RC_US"*}" rest="${rec#*"$RC_US"}"
        [[ "$c" == "$1" ]] && printf '%s\n' "${rest%%"$RC_US"*}"
    done <<< "$RC_PARSED"
}

rc_route_classes() {  # -> newline list of declared route-class names
    local rec
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        local c="${rec%%"$RC_US"*}"
        [[ "$c" == route_classes.* ]] && printf '%s\n' "${c#route_classes.}"
    done <<< "$RC_PARSED" | sort -u
}

rc_array_elems() {  # <ctx> <key> -> newline list of array elements
    local v
    v=$(rc_get "$1" "$2") || return 1
    [[ -z "$v" ]] && return 0
    printf '%s' "$v" | tr "$RC_RS" '\n'
}

_rc_in_list() {  # <needle> <space-separated list>
    local x
    for x in $2; do [[ "$x" == "$1" ]] && return 0; done
    return 1
}

# ── defense-in-depth secret scan (decision 3) ────────────────────────
# Catches obvious value-shaped secrets in ANY field. Not complete
# secret detection — the structural boundary above is the guarantee.
rc_secretish() {  # <value> -> 0 when the value looks like a secret
    local v="$1"
    [[ "$v" =~ ^sk-[A-Za-z0-9_-]{8,} ]] && return 0
    [[ "$v" =~ [Bb]earer[[:space:]]+[A-Za-z0-9._~+/-]+=* ]] && return 0
    [[ "$v" == *"-----BEGIN "*"PRIVATE KEY"* ]] && return 0
    [[ "$v" =~ ^[0-9a-fA-F]{32,}$ ]] && return 0
    [[ "$v" =~ ^[A-Za-z0-9+/]{40,}={0,2}$ ]] && return 0
    return 1
}

# ── validate ─────────────────────────────────────────────────────────
# rc_validate <file>
# Prints one named violation per line (grammar first, then semantic);
# exit 0 = valid, 1 = violations, 2 = unreadable file.
rc_validate() {
    local file="$1" bad=0
    [[ -r "$file" ]] || { echo "routing.toml: cannot read '$file'"; return 2; }
    rc_parse "$file" || true
    if [[ -n "$RC_ERRORS" ]]; then
        printf '%s' "$RC_ERRORS" | sed 's/^/routing.toml: /'
        bad=1
    fi

    local viol
    viol() { echo "routing.toml: $1"; bad=1; }

    # root
    local sv
    if sv=$(rc_get root schema_version); then
        [[ "$sv" == "1" ]] || viol "schema_version $sv is not supported (this build implements 1)"
    else
        viol "schema_version = 1 is required before the first table"
    fi

    # secret scan over every parsed string / array element
    local rec
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        local c="${rec%%"$RC_US"*}" rest="${rec#*"$RC_US"}"
        local k="${rest%%"$RC_US"*}" rest2="${rest#*"$RC_US"}"
        local t="${rest2%%"$RC_US"*}" v="${rest2#*"$RC_US"}"
        local e
        if [[ "$t" == "array" ]]; then
            while IFS= read -r e; do
                [[ -n "$e" ]] && rc_secretish "$e" && viol "[$c] $k: a value-shaped secret is never accepted in the registry (reference credentials by environment-variable NAME)"
            done <<< "$(printf '%s' "$v" | tr "$RC_RS" '\n')"
        elif [[ "$t" == "string" ]]; then
            rc_secretish "$v" && viol "[$c] $k: a value-shaped secret is never accepted in the registry (reference credentials by environment-variable NAME)"
        fi
    done <<< "$RC_PARSED"

    # [policy]
    local k
    while IFS= read -r k; do
        [[ -z "$k" ]] && continue
        if _rc_in_list "$k" "$RC_POLICY_FUTURE_KEYS"; then
            viol "[policy] '$k' is not supported in increment A (its behavior arrives with the failover/recovery increments) — a key nothing enforces is refused, never accepted as inert configuration"
        elif ! _rc_in_list "$k" "$RC_POLICY_KEYS"; then
            viol "[policy] unknown key '$k'"
        fi
    done <<< "$(rc_keys policy)"
    local pv
    if pv=$(rc_get policy enabled); then
        [[ "$(rc_type policy enabled)" == "bool" ]] || viol "[policy] enabled must be a boolean"
    fi

    # [route_classes.*]
    local cls
    while IFS= read -r cls; do
        [[ -z "$cls" ]] && continue
        while IFS= read -r k; do
            [[ -z "$k" ]] && continue
            [[ "$k" == "tier_order" ]] || viol "[route_classes.$cls] unknown key '$k'"
        done <<< "$(rc_keys "route_classes.$cls")"
        if [[ "$(rc_type "route_classes.$cls" tier_order 2>/dev/null)" != "array" ]]; then
            viol "[route_classes.$cls] tier_order must be an array of tiers"
        else
            local seen=" " tier n=0
            while IFS= read -r tier; do
                [[ -z "$tier" ]] && continue
                n=$((n+1))
                _rc_in_list "$tier" "$RC_TIERS" || viol "[route_classes.$cls] tier_order references unknown tier '$tier' (tiers are closed: $RC_TIERS)"
                [[ "$seen" == *" $tier "* ]] && viol "[route_classes.$cls] tier_order repeats '$tier'"
                seen="$seen$tier "
            done <<< "$(rc_array_elems "route_classes.$cls" tier_order)"
            [[ "$n" -eq 0 ]] && viol "[route_classes.$cls] tier_order must not be empty"
        fi
    done <<< "$(rc_route_classes)"

    # [[profiles]]
    local i=0 ids=$'\n' id v
    while [[ $i -lt $RC_PROFILE_COUNT ]]; do
        local ctx="profiles.$i" label
        id=$(rc_get "$ctx" id 2>/dev/null) || id=""
        label="profile #$((i+1))${id:+ ('$id')}"
        while IFS= read -r k; do
            [[ -z "$k" ]] && continue
            _rc_in_list "$k" "$RC_PROFILE_REQUIRED $RC_PROFILE_OPTIONAL" || viol "$label: unknown key '$k'"
        done <<< "$(rc_keys "$ctx")"
        for k in $RC_PROFILE_REQUIRED; do
            rc_get "$ctx" "$k" >/dev/null 2>&1 || viol "$label: missing required key '$k'"
        done
        if [[ -n "$id" ]]; then
            [[ "$id" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || viol "$label: id must be lowercase [a-z0-9._-]"
            if [[ "$ids" == *$'\n'"$id"$'\n'* ]]; then viol "duplicate profile id '$id'"; else ids="${ids}${id}"$'\n'; fi
        fi
        if v=$(rc_get "$ctx" backend); then
            _rc_in_list "$v" "$RC_BACKENDS" || viol "$label: backend '$v' is not a known harness backend ($RC_BACKENDS)"
        fi
        if v=$(rc_get "$ctx" capability_tier); then
            _rc_in_list "$v" "$RC_TIERS" || viol "$label: capability_tier '$v' is not a tier (tiers are closed: $RC_TIERS)"
        fi
        if v=$(rc_get "$ctx" priority); then
            [[ "$(rc_type "$ctx" priority)" == "int" && "$v" -gt 0 ]] || viol "$label: priority must be a positive integer"
        fi
        if rc_get "$ctx" roles >/dev/null 2>&1; then
            if [[ "$(rc_type "$ctx" roles)" != "array" ]]; then
                viol "$label: roles must be an array"
            else
                local role n=0
                while IFS= read -r role; do
                    [[ -z "$role" ]] && continue
                    n=$((n+1))
                    _rc_in_list "$role" "$RC_ROLES" || viol "$label: unknown role '$role' (roles: $RC_ROLES)"
                done <<< "$(rc_array_elems "$ctx" roles)"
                [[ "$n" -eq 0 ]] && viol "$label: roles must not be empty"
            fi
        fi
        if v=$(rc_get "$ctx" data_policy); then
            _rc_in_list "$v" "$RC_DATA_POLICIES" || viol "$label: data_policy '$v' is not accepted ($RC_DATA_POLICIES)"
        fi
        local has_mode=0 has_env=0
        rc_get "$ctx" credential_mode >/dev/null 2>&1 && has_mode=1
        rc_get "$ctx" credential_env  >/dev/null 2>&1 && has_env=1
        [[ $((has_mode + has_env)) -eq 1 ]] || viol "$label: exactly one of credential_mode | credential_env is required (references only — never values)"
        if [[ $has_env -eq 1 ]]; then
            v=$(rc_get "$ctx" credential_env)
            [[ "$v" =~ ^[A-Z_][A-Z0-9_]*$ ]] || viol "$label: credential_env must be an environment-variable NAME ([A-Z_][A-Z0-9_]*)"
        fi
        local has_url=0 has_url_env=0
        rc_get "$ctx" base_url     >/dev/null 2>&1 && has_url=1
        rc_get "$ctx" base_url_env >/dev/null 2>&1 && has_url_env=1
        [[ $((has_url + has_url_env)) -le 1 ]] || viol "$label: at most one of base_url | base_url_env"
        if [[ $has_url -eq 1 ]]; then
            v=$(rc_get "$ctx" base_url)
            [[ "$v" =~ ^https?:// ]] || viol "$label: base_url must be an absolute http(s) URL"
        fi
        if [[ $has_url_env -eq 1 ]]; then
            v=$(rc_get "$ctx" base_url_env)
            [[ "$v" =~ ^[A-Z_][A-Z0-9_]*$ ]] || viol "$label: base_url_env must be an environment-variable NAME ([A-Z_][A-Z0-9_]*)"
        fi
        i=$((i+1))
    done

    # cross-references
    if v=$(rc_get policy preferred_profile); then
        [[ "$ids" == *$'\n'"$v"$'\n'* ]] || viol "[policy] preferred_profile '$v' does not name a declared profile"
    fi

    [[ $bad -eq 0 ]]
}
