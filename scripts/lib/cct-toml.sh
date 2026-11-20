#!/usr/bin/env bash
# cct-toml.sh — the constrained-TOML line lexer shared by CCT's
# registries: routing.toml (routing-config.sh) and llms.toml
# (llm-catalog.sh). Extracted from routing-config.sh for #479 (#400 D4).
#
# A registry accepts ONLY the TOML subset lexed here; anything else is
# REJECTED BY NAME, never approximated. This file knows lines and
# values, not tables: which table headers and which keys are accepted is
# each registry's own vocabulary and stays in its own file.
#   - key = value with bare keys [A-Za-z0-9_-]+
#   - values: single-line basic strings ("...", the only escape is \"),
#     integers, booleans, single-line arrays of basic strings
# Rejected by name: dotted keys, inline tables, multiline strings,
# literal (single-quoted) strings, non-string arrays, malformed quoting,
# and any other value form.
#
# bash 3.2 compatible; no dependencies. Every function returns its
# result in globals, so no caller needs a subshell.

CT_US=$'\x1f'   # field separator of a parsed record
CT_RS=$'\x1e'   # element separator inside an array value

# ct_trim <raw>
# Sets CT_LINE to the line without leading and trailing whitespace.
ct_trim() {
    CT_LINE="${1#"${1%%[![:space:]]*}"}"
    CT_LINE="${CT_LINE%"${CT_LINE##*[![:space:]]}"}"
}

# ct_split_kv <line>
# Sets CT_KEY and CT_VAL. Returns 1 with CT_ERR set when the line is not
# `key = value` or the key is dotted.
ct_split_kv() {
    CT_KEY=""
    CT_VAL=""
    CT_ERR=""
    if [[ ! "$1" =~ ^([A-Za-z0-9_.-]+)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
        CT_ERR="unrecognized line (not a comment, table header, or key = value): '$1'"
        return 1
    fi
    CT_KEY="${BASH_REMATCH[1]}"
    CT_VAL="${BASH_REMATCH[2]}"
    if [[ "$CT_KEY" == *.* ]]; then
        CT_ERR="dotted keys are not accepted: '$CT_KEY'"
        return 1
    fi
    return 0
}

# ct_lex_value <value>
# Sets CT_TYPE (string | bool | int | array) and CT_VALUE (array
# elements joined with CT_RS). Returns 1 with CT_ERR set for a rejected
# form; the unsupported forms are rejected BY NAME first.
ct_lex_value() {
    local val="$1"
    CT_TYPE=""
    CT_VALUE=""
    CT_ERR=""
    case "$val" in
        '"""'*) CT_ERR="multiline strings are not accepted"; return 1 ;;
        "'"*)   CT_ERR="literal (single-quoted) strings are not accepted"; return 1 ;;
        "{"*)   CT_ERR="inline tables are not accepted"; return 1 ;;
    esac
    if [[ "$val" =~ ^\"([^\"\\]|\\\")*\"$ ]]; then
        local s="${val:1:${#val}-2}"
        CT_TYPE="string"
        CT_VALUE="${s//\\\"/\"}"
    elif [[ "$val" == "true" || "$val" == "false" ]]; then
        CT_TYPE="bool"
        CT_VALUE="$val"
    elif [[ "$val" =~ ^-?[0-9]+$ ]]; then
        CT_TYPE="int"
        CT_VALUE="$val"
    elif [[ "${val:0:1}" == "[" ]]; then
        if [[ ! "$val" =~ ^\[[[:space:]]*(\"([^\"\\]|\\\")*\"([[:space:]]*,[[:space:]]*\"([^\"\\]|\\\")*\")*[[:space:]]*)?\]$ ]]; then
            CT_ERR="only single-line arrays of basic strings are accepted: '$val'"
            return 1
        fi
        local inner="${val:1:${#val}-2}" elems="" e rest
        rest="$inner"
        while [[ "$rest" =~ ^[[:space:]]*\"(([^\"\\]|\\\")*)\"[[:space:]]*(,(.*))?$ ]]; do
            e="${BASH_REMATCH[1]}"; e="${e//\\\"/\"}"
            elems="${elems}${e}${CT_RS}"
            rest="${BASH_REMATCH[4]}"
            [[ -z "${BASH_REMATCH[3]}" ]] && rest=""
            [[ -z "$rest" ]] && break
        done
        CT_TYPE="array"
        CT_VALUE="${elems%"$CT_RS"}"
    elif [[ "$val" == *'"'* ]]; then
        CT_ERR="malformed quoting: '$val'"
        return 1
    else
        CT_ERR="unrecognized value form: '$val' (basic string, integer, boolean, or array of basic strings)"
        return 1
    fi
    return 0
}

# ── defense-in-depth secret scan ─────────────────────────────────────
# Catches obvious value-shaped secrets in ANY field. Not complete secret
# detection: a registry's structural rule (a credential is named by its
# environment variable, never held as a value) is the guarantee.
ct_secretish() {  # <value> -> 0 when the value looks like a secret
    local v="$1"
    [[ "$v" =~ ^sk-[A-Za-z0-9_-]{8,} ]] && return 0
    [[ "$v" =~ [Bb]earer[[:space:]]+[A-Za-z0-9._~+/-]+=* ]] && return 0
    [[ "$v" == *"-----BEGIN "*"PRIVATE KEY"* ]] && return 0
    [[ "$v" =~ ^[0-9a-fA-F]{32,}$ ]] && return 0
    [[ "$v" =~ ^[A-Za-z0-9+/]{40,}={0,2}$ ]] && return 0
    return 1
}
