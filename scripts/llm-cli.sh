#!/usr/bin/env bash
# llm-cli.sh — `cct llm`: read-only views of the LLM catalog (#479, the
# launch-first slice of #400).
#
#   cct llm list              the targets --llm accepts, and whether each
#                             can be launched now
#   cct llm validate [file]   check the catalog (default: the one in the
#                             CCT home); every violation by line and name
#
# Nothing here starts a harness or reads a credential's value: a
# credential is reported by its variable's NAME and whether it is set,
# and an endpoint by its origin (scheme://host[:port]) alone.
#
# Exit codes: 0 ok; 1 the catalog has violations; 2 usage, or no
# readable catalog.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/llm-catalog.sh
source "$SCRIPT_DIR/lib/llm-catalog.sh"
# shellcheck source=lib/llm-adapters/claude-code.sh
source "$SCRIPT_DIR/lib/llm-adapters/claude-code.sh"

LLM_EXAMPLE_REL="shared/templates/llm/llms.toml.example"

usage() {
    cat <<'EOF'
cct llm — the LLM catalog: named targets for --llm

USAGE
  cct llm list              the targets --llm accepts, and whether each can
                            be launched now
  cct llm validate [file]   check the catalog (default: llms.toml in the CCT
                            home); every violation by line and name

Start a session on a target:
  cct start --llm <target> [path]      (or: claude-code --llm <target> [path])

A target is <llm>, or <llm>@<binding> when an llm has several bindings.
The catalog is ${CCT_HOME:-~/.cct}/llms.toml; docs/llm-catalog.md describes it.
EOF
}

no_catalog() {  # <path>
    echo "cct llm: no LLM catalog at $1" >&2
    echo "Copy $LLM_EXAMPLE_REL from your checkout there and edit it; docs/llm-catalog.md describes the file." >&2
}

cmd_validate() {
    local file="${1:-}" rc=0
    if [[ -z "$file" ]]; then
        file="$(lc_catalog_path)"
        if [[ ! -e "$file" ]]; then no_catalog "$file"; return 2; fi
    fi
    lc_validate "$file" || rc=$?
    case "$rc" in
        0) echo "OK: $file is a valid LLM catalog" ;;
        1) echo "$LC_VIOLATIONS violation(s) in $file" >&2 ;;
    esac
    return "$rc"
}

# One row per binding, and one for an llm nothing binds.
_row() {  # target harness model endpoint credential state
    ROWS="${ROWS}$1${CT_US}$2${CT_US}$3${CT_US}$4${CT_US}$5${CT_US}$6"$'\n'
}

cmd_list() {
    local file l b bl h model e ep mode cred endpoint credential state target n rc=0
    file="$(lc_catalog_path)"
    if [[ ! -e "$file" ]]; then no_catalog "$file"; return 2; fi
    lc_validate "$file" >&2 || rc=$?
    if [[ $rc -eq 1 ]]; then
        echo "cct llm: $file has $LC_VIOLATIONS violation(s); fix them first (cct llm validate)" >&2
        return 1
    elif [[ $rc -ne 0 ]]; then
        return 2
    fi

    ROWS=""
    while IFS= read -r l; do
        [[ -z "$l" ]] && continue
        model=$(lc_get "llms.$l" model) || model=""
        n=0
        while IFS= read -r b; do
            [[ -z "$b" ]] && continue
            bl=$(lc_get "bindings.$b" llm) || bl=""
            [[ "$bl" == "$l" ]] || continue
            n=$((n + 1))
            h=$(lc_get "bindings.$b" harness) || h=""
            # <llm> alone is a target only while it has one binding for the harness.
            target="$l"
            if ! lc_resolve "$h" "$l"; then target="$l@$b"; fi

            llm_cc_plan "$b"
            if e=$(lc_get "bindings.$b" endpoint); then
                endpoint="endpoint $e"
                if lc_endpoint_url "$e"; then endpoint="$(rt_sanitize_origin "$LC_URL")"; fi
                ep=$(lc_get "endpoints.$e" provider) || ep=""
                mode=$(lc_get "providers.$ep" credential_mode) || mode=""
                cred=$(lc_get "providers.$ep" credential_env) || cred=""
                if [[ "$mode" == "env" ]]; then
                    if [[ "$cred" =~ $LC_ENV_NAME_RE && -n "${!cred:-}" ]]; then
                        credential="$cred (set)"
                    else
                        credential="$cred (not set)"
                    fi
                else
                    credential="none"
                fi
            else
                endpoint="-"
                credential="its own login"
            fi
            state="$LLM_CC_STATE"
            if [[ -n "$LLM_CC_REASON" ]]; then state="$state: $LLM_CC_REASON"; fi
            _row "$target" "$h" "$model" "$endpoint" "$credential" "$state"
        done <<< "$(lc_ids bindings)"
        if [[ $n -eq 0 ]]; then
            _row "$l" "-" "$model" "-" "-" "no binding: add a [bindings.<id>] table for it"
        fi
    done <<< "$(lc_ids llms)"

    if [[ -z "$ROWS" ]]; then
        echo "The catalog at $file defines no llm."
        return 0
    fi
    _print_rows
    echo ""
    echo "unverified: launchable; no compatibility probe exists yet, so nothing has checked the model against the harness."
    echo "Start a session on one:  cct start --llm <target> [path]"
    return 0
}

_print_rows() {
    local header="TARGET${CT_US}HARNESS${CT_US}MODEL${CT_US}ENDPOINT${CT_US}CREDENTIAL${CT_US}STATE"
    local w1=0 w2=0 w3=0 w4=0 w5=0 rec f1 f2 f3 f4 f5 f6 rest
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        f1="${rec%%"$CT_US"*}"; rest="${rec#*"$CT_US"}"
        f2="${rest%%"$CT_US"*}"; rest="${rest#*"$CT_US"}"
        f3="${rest%%"$CT_US"*}"; rest="${rest#*"$CT_US"}"
        f4="${rest%%"$CT_US"*}"; rest="${rest#*"$CT_US"}"
        f5="${rest%%"$CT_US"*}"
        [[ ${#f1} -gt $w1 ]] && w1=${#f1}
        [[ ${#f2} -gt $w2 ]] && w2=${#f2}
        [[ ${#f3} -gt $w3 ]] && w3=${#f3}
        [[ ${#f4} -gt $w4 ]] && w4=${#f4}
        [[ ${#f5} -gt $w5 ]] && w5=${#f5}
    done <<< "$header"$'\n'"$ROWS"
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        f1="${rec%%"$CT_US"*}"; rest="${rec#*"$CT_US"}"
        f2="${rest%%"$CT_US"*}"; rest="${rest#*"$CT_US"}"
        f3="${rest%%"$CT_US"*}"; rest="${rest#*"$CT_US"}"
        f4="${rest%%"$CT_US"*}"; rest="${rest#*"$CT_US"}"
        f5="${rest%%"$CT_US"*}"; f6="${rest#*"$CT_US"}"
        printf "%-${w1}s  %-${w2}s  %-${w3}s  %-${w4}s  %-${w5}s  %s\n" "$f1" "$f2" "$f3" "$f4" "$f5" "$f6"
    done <<< "$header"$'\n'"$ROWS"
    return 0
}

cmd="${1:-help}"
[[ $# -gt 0 ]] && shift
case "$cmd" in
    list)
        if [[ $# -gt 0 ]]; then echo "cct llm list takes no arguments" >&2; exit 2; fi
        cmd_list
        ;;
    validate)
        if [[ $# -gt 1 ]]; then echo "cct llm validate takes at most one file" >&2; exit 2; fi
        cmd_validate "${1:-}"
        ;;
    help|-h|--help) usage ;;
    *) echo "cct llm: unknown command '$cmd' (list | validate)" >&2; usage >&2; exit 2 ;;
esac
