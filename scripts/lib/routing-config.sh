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
RC_POLICY_KEYS="enabled preferred_profile failback healthy_probes_required minimum_profile_dwell_sec"
RC_POLICY_FUTURE_KEYS="max_switches_per_task"
RC_HEALTHY_PROBES_REQUIRED_DEFAULT=2
RC_MINIMUM_PROFILE_DWELL_SEC_DEFAULT=300
RC_FAILBACK_DEFAULT="auto"

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

rc_index_of() {  # <profile-id> -> index (rc 1 when absent)
    local i=0
    while [[ $i -lt $RC_PROFILE_COUNT ]]; do
        if [[ "$(rc_get "profiles.$i" id 2>/dev/null)" == "$1" ]]; then
            printf '%s' "$i"; return 0
        fi
        i=$((i+1))
    done
    return 1
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
            viol "[policy] '$k' is not implemented by an owning increment — a key nothing enforces is refused, never accepted as inert configuration"
        elif ! _rc_in_list "$k" "$RC_POLICY_KEYS"; then
            viol "[policy] unknown key '$k'"
        fi
    done <<< "$(rc_keys policy)"
    local pv
    if pv=$(rc_get policy enabled); then
        [[ "$(rc_type policy enabled)" == "bool" ]] || viol "[policy] enabled must be a boolean"
    fi
    if pv=$(rc_get policy healthy_probes_required); then
        [[ "$(rc_type policy healthy_probes_required)" == "int" && "$pv" -ge 1 ]] \
            || viol "[policy] healthy_probes_required must be an integer >= 1"
    fi
    if pv=$(rc_get policy minimum_profile_dwell_sec); then
        [[ "$(rc_type policy minimum_profile_dwell_sec)" == "int" && "$pv" -ge 0 ]] \
            || viol "[policy] minimum_profile_dwell_sec must be an integer >= 0"
    fi
    if pv=$(rc_get policy failback); then
        [[ "$(rc_type policy failback)" == "string" && ( "$pv" == "auto" || "$pv" == "operator" ) ]] \
            || viol "[policy] failback must be 'auto' or 'operator'"
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

# ── effective policy (#248 T4, plan decision 4) ──────────────────────
# rc_profile_tuple <idx> — the COMPLETE EXECUTABLE IDENTITY of one
# registry profile as CANONICAL compact JSON. The monotonic subset
# invariant compares THESE, not friendly ids: a candidate is what it
# executes as (backend+provider+model+tier+pool+credential reference+
# endpoint reference+roles+tool profile+data policy), so no
# composition step can keep an id while changing what it runs.
# Canonical means COLLISION-FREE, not merely deterministic: a naive
# delimiter join would let two structurally different candidates
# compare equal when a field carries the delimiter — JSON gives
# unambiguous boundaries and escaping. `roles` is semantically a SET
# (order carries no routing meaning) and is sorted/uniqued before
# serialization.
rc_profile_tuple() {
    local ctx="profiles.$1" cred ep roles_json
    if cred=$(rc_get "$ctx" credential_mode 2>/dev/null); then cred="mode:$cred"
    elif cred=$(rc_get "$ctx" credential_env 2>/dev/null); then cred="env:$cred"
    else cred="none"; fi
    if ep=$(rc_get "$ctx" base_url 2>/dev/null); then ep="url:$ep"
    elif ep=$(rc_get "$ctx" base_url_env 2>/dev/null); then ep="urlenv:$ep"
    else ep="none"; fi
    roles_json=$(rc_array_elems "$ctx" roles | sort -u | jq -R . | jq -sc .)
    jq -nc \
        --arg id "$(rc_get "$ctx" id)" --arg backend "$(rc_get "$ctx" backend)" \
        --arg provider "$(rc_get "$ctx" provider)" --arg model "$(rc_get "$ctx" model)" \
        --arg tier "$(rc_get "$ctx" capability_tier)" \
        --argjson priority "$(rc_get "$ctx" priority)" \
        --arg pool "$(rc_get "$ctx" quota_pool)" --argjson roles "$roles_json" \
        --arg tool "$(rc_get "$ctx" tool_profile)" --arg dp "$(rc_get "$ctx" data_policy)" \
        --arg cred "$cred" --arg ep "$ep" \
        '[$id, $backend, $provider, $model, $tier, $priority, $pool, $roles, $tool, $dp, $cred, $ep]'
}

# rc_effective <registry-file> <automation-json-file|->
# The most-restrictive combination of the two layers:
#   - refuses to compose over an invalid registry;
#   - re-checks (defense in depth) that the repo routing block carries
#     ONLY the closed restriction keys — a merge must never consume a
#     block the standalone validator would refuse;
#   - enabled = user [policy].enabled AND repo routing.enabled (each
#     defaulting true when absent — the registry's presence is the
#     user's opt-in, an absent repo block is no restriction); when the
#     effective policy is DISABLED the candidate set is EMPTY;
#   - candidates = registry profiles ∩ repo allowed_profiles (absent =
#     all), each emitted as its full executable-identity tuple;
#   - a repo-listed id the registry does not define, and a
#     default_task_route naming no registry route class, are NAMED
#     violations — a typo must never silently widen or narrow policy.
# Output: violations (exit 1) or the effective JSON document (exit 0).
rc_effective() {
    local reg="$1" repo="$2" bad=0
    local viol
    viol() { echo "effective-policy: $1"; bad=1; }

    if ! rc_validate "$reg" >/dev/null 2>&1; then
        viol "the registry does not validate — refusing to compose an effective policy over an invalid registry (run: cct routing validate)"
        echo ""
        return 1
    fi
    rc_parse "$reg" || true

    local rblock="null"
    if [[ "$repo" != "-" ]]; then
        [[ -r "$repo" ]] || { viol "cannot read '$repo'"; return 1; }
        rblock=$(jq -c '.routing // null' "$repo" 2>/dev/null) || { viol "'$repo' is not valid JSON"; return 1; }
    fi
    if [[ "$rblock" != "null" ]]; then
        local k
        for k in $(jq -r 'keys[]' <<< "$rblock" 2>/dev/null); do
            case "$k" in
                enabled|allowed_profiles|default_task_route) ;;
                tier2) ;;     # promoted with #254 T6 (restriction-only; validated below)
                recovery) ;;  # promoted with #257 D T3 (restriction-only; validated below)
                *) viol "the repo routing block carries a non-restriction key '$k' — a repository can narrow user routing authority, never create it (validate-automation-config refuses this block)" ;;
            esac
        done
    fi
    [[ $bad -ne 0 ]] && return 1

    # both-layers-enable
    local u_en r_en enabled=true
    u_en=$(rc_get policy enabled 2>/dev/null) || u_en="true"
    # NB: jq's // would turn an explicit false back into true (it
    # treats false as empty) — the null test must be explicit.
    r_en=$(jq -r 'if . == null or (.enabled == null) then "true" else (.enabled | tostring) end' <<< "$rblock")
    [[ "$u_en" == "true" && "$r_en" == "true" ]] || enabled=false

    # allowed set = intersection; unknown repo ids are NAMED
    local allowed="" i id
    local repo_ids
    repo_ids=$(jq -r 'if . == null or (.allowed_profiles == null) then "" else .allowed_profiles[] end' <<< "$rblock")
    if [[ -n "$repo_ids" ]]; then
        local rid found
        while IFS= read -r rid; do
            [[ -z "$rid" ]] && continue
            found=false
            i=0
            while [[ $i -lt $RC_PROFILE_COUNT ]]; do
                [[ "$(rc_get "profiles.$i" id)" == "$rid" ]] && found=true
                i=$((i+1))
            done
            [[ "$found" == "true" ]] || viol "repo allowed_profiles names '$rid', which the user registry does not define — refusing to guess (a typo must not silently change policy)"
        done <<< "$repo_ids"
    fi
    # default route class must exist in the registry
    local dtr
    dtr=$(jq -r 'if . == null then "" else (.default_task_route // "") end' <<< "$rblock")
    if [[ -n "$dtr" ]]; then
        rc_route_classes | grep -qx "$dtr" || viol "repo default_task_route '$dtr' names no route class in the user registry"
    fi
    [[ $bad -ne 0 ]] && return 1

    # emit the effective document: full tuples, empty when disabled
    local out="[]"
    if [[ "$enabled" == "true" ]]; then
        i=0
        while [[ $i -lt $RC_PROFILE_COUNT ]]; do
            id=$(rc_get "profiles.$i" id)
            if [[ -z "$repo_ids" ]] || grep -qx "$id" <<< "$repo_ids"; then
                out=$(jq -c --argjson t "$(rc_profile_tuple "$i")" '. + [$t]' <<< "$out")
            fi
            i=$((i+1))
        done
    fi
    # tier2 delegation (#254 T6, promoted refused->implemented->tested):
    # RESTRICTION-ONLY — a repository may FORBID Tier-2 delegation
    # (routing.tier2.delegation_enabled = false); it can never widen
    # what the user registry permits. Absent (and explicit true) mean
    # "not restricted". The explicit-null discipline mirrors `enabled`
    # (jq's // would turn an explicit false back into true).
    local t2_allowed=true
    if [[ "$(jq -r 'if . == null or (.tier2 == null) or (.tier2.delegation_enabled == null) then "true" else (.tier2.delegation_enabled | tostring) end' <<< "$rblock")" == "false" ]]; then
        t2_allowed=false
    fi

    # recovery wake (#257 D T3, promoted refused->implemented->tested):
    # RESTRICTION-ONLY — a repository may FORBID `routing tick --wake`
    # from relaunching its own parked routed runs
    # (routing.recovery.wake_enabled = false). Same explicit-null
    # discipline as `enabled` and tier2.
    local wake_allowed=true
    if [[ "$(jq -r 'if . == null or (.recovery == null) or (.recovery.wake_enabled == null) then "true" else (.recovery.wake_enabled | tostring) end' <<< "$rblock")" == "false" ]]; then
        wake_allowed=false
    fi
    local auto_failback_allowed=true
    if [[ "$(jq -r 'if . == null or (.recovery == null) or (.recovery.auto_failback_enabled == null) then "true" else (.recovery.auto_failback_enabled | tostring) end' <<< "$rblock")" == "false" ]]; then
        auto_failback_allowed=false
    fi

    jq -n --argjson en "$([[ "$enabled" == "true" ]] && echo true || echo false)" \
          --argjson cands "$out" --arg dtr "$dtr" \
          --argjson t2 "$([[ "$t2_allowed" == "true" ]] && echo true || echo false)" \
          --argjson wk "$([[ "$wake_allowed" == "true" ]] && echo true || echo false)" \
          --argjson af "$([[ "$auto_failback_allowed" == "true" ]] && echo true || echo false)" \
          '{enabled: $en, candidates: $cands,
            default_task_route: (if $dtr == "" then null else $dtr end),
            tier2_delegation_allowed: $t2, wake_allowed: $wk,
            auto_failback_allowed: $af}'
}

# rc_wake_allowed <effective-json> — THE shared read of the promoted
# recovery restriction (#257 D T3). Explicit-null discipline: an
# explicit false must stay false (jq's // would widen it to true).
rc_wake_allowed() {
    jq -r 'if .wake_allowed == null then true else .wake_allowed end' <<< "$1"
}

rc_auto_failback_allowed() {
    jq -r 'if .auto_failback_allowed == null then true else .auto_failback_allowed end' <<< "$1"
}

rc_healthy_probes_required() {
    local v
    v=$(rc_get policy healthy_probes_required 2>/dev/null || echo "")
    printf '%s\n' "${v:-$RC_HEALTHY_PROBES_REQUIRED_DEFAULT}"
}

rc_minimum_profile_dwell_sec() {
    local v
    v=$(rc_get policy minimum_profile_dwell_sec 2>/dev/null || echo "")
    printf '%s\n' "${v:-$RC_MINIMUM_PROFILE_DWELL_SEC_DEFAULT}"
}

rc_failback_policy() {
    local v
    v=$(rc_get policy failback 2>/dev/null || echo "")
    printf '%s\n' "${v:-$RC_FAILBACK_DEFAULT}"
}

# rc_tier2_allowed <effective-json> — THE shared read of the promoted
# tier2 restriction (#254 T6), used by the CLI's task-addressed
# explain AND the supervisor's --delegate refusal so the two surfaces
# can never drift. Explicit-null discipline: an explicit false must
# stay false (jq's // would silently widen it back to true).
rc_tier2_allowed() {
    jq -r 'if .tier2_delegation_allowed == null then true else .tier2_delegation_allowed end' <<< "$1"
}
