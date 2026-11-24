#!/usr/bin/env bash
# llm-cli.sh — `cct llm` and `cct harness explain`: read-only views of the
# LLM catalog (#479, the launch-first slice of #400; #400 S1).
#
#   cct llm list [--json]              the targets --llm accepts, and whether
#                                      each can be launched now
#   cct llm show <llm> [--json]        one llm: its provider, its model and
#                                      what each of its bindings would launch
#   cct llm validate [file] [--json]   check the catalog (default: the one in
#                                      the CCT home); every violation by line
#                                      and name
#   cct harness explain <harness> --llm <target> [--json]
#                                      the launch plan: what a launch would
#                                      set and remove, by name, its digests,
#                                      and why it would be refused
#
# Nothing here starts a harness or reads a credential's value: a credential
# is reported by its variable's NAME and whether it is set, and an endpoint
# by its origin (scheme://host[:port]) alone. A target is planned by the
# resolver the launcher uses (lib/llm-resolve.sh), so an explanation and a
# launch cannot disagree. `--json` output is described by
# shared/schemas/llm-catalog-cli.schema.json. A command that cannot answer
# (no catalog, a catalog with violations, an llm the catalog does not
# define) prints under --json the envelope with an error field, alone, and
# exits as its text form does.
#
# Exit codes: 0 ok; 1 the catalog has violations; 2 usage, or no readable
# catalog; 3 `explain` of a launch that would be refused.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/llm-catalog.sh
source "$SCRIPT_DIR/lib/llm-catalog.sh"
# shellcheck source=lib/llm-adapters/claude-code.sh
source "$SCRIPT_DIR/lib/llm-adapters/claude-code.sh"
# shellcheck source=lib/llm-resolve.sh
source "$SCRIPT_DIR/lib/llm-resolve.sh"

LLM_EXAMPLE_REL="shared/templates/llm/llms.toml.example"
LLM_NO_CATALOG="no LLM catalog"
EXIT_REFUSED=3

usage() {
    cat <<'EOF'
cct llm — the LLM catalog: named targets for --llm

USAGE
  cct llm list [--json]             the targets --llm accepts, and whether
                                    each can be launched now
  cct llm show <llm> [--json]       one llm, its provider and model, and what
                                    each of its bindings would launch
  cct llm validate [file] [--json]  check the catalog (default: llms.toml in
                                    the CCT home); every violation by line
                                    and name
  cct harness explain <harness> --llm <target> [--json]
                                    what a launch would set and remove, by
                                    name, and why it would be refused

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

envelope() {  # <command> <json object> -> the object with schema_version and command first
    jq -c --argjson v "$LR_PLAN_SCHEMA_VERSION" --arg c "$1" '{schema_version: $v, command: $c} + .' <<< "$2"
}

json_error() {  # <command> <message>: the envelope of a command that cannot answer
    envelope "$1" "$(jq -nc --arg f "$CATALOG" --arg e "$2" '{catalog: $f, error: $e}')"
}

# The catalog in the CCT home, parsed and valid (in THIS shell, for the
# resolver), or the exit code: 2 when there is none or it cannot be read,
# 1 when it has violations. Said on stderr, or under --json by the error
# envelope alone.
load_catalog() {  # <command> <json>
    local rc=0 msg=""
    CATALOG="$(lc_catalog_path)"
    if [[ ! -e "$CATALOG" ]]; then
        if [[ "$2" == 1 ]]; then json_error "$1" "$LLM_NO_CATALOG"; else no_catalog "$CATALOG"; fi
        return 2
    fi
    if [[ "$2" == 1 ]]; then lc_validate "$CATALOG" >/dev/null || rc=$?; else lc_validate "$CATALOG" >&2 || rc=$?; fi
    case "$rc" in
        0) return 0 ;;
        1) msg="$CATALOG has $LC_VIOLATIONS violation(s); fix them first (cct llm validate)" ;;
        *) rc=2; if [[ "$2" == 1 ]]; then msg=$(lc_validate "$CATALOG"); fi ;;  # its words, from a second run
    esac
    if [[ "$2" == 1 ]]; then json_error "$1" "$msg"
    elif [[ -n "$msg" ]]; then echo "cct llm: $msg" >&2
    fi
    return "$rc"
}

null_if_empty() { if [[ -z "$1" ]]; then printf 'null'; else jq -nc --arg v "$1" '$v'; fi; }

cmd_validate() {
    local file="${1:-}" json="$2" rc=0 out
    if [[ -z "$file" ]]; then
        file="$(lc_catalog_path)"
        if [[ ! -e "$file" ]]; then
            if [[ "$json" == 1 ]]; then
                envelope validate "$(jq -nc --arg f "$file" --arg e "$LLM_NO_CATALOG" '{file: $f, valid: false, violations: [], error: $e}')"
            else
                no_catalog "$file"
            fi
            return 2
        fi
    fi
    if [[ "$json" == 1 ]]; then
        local error='null'
        out=$(lc_validate "$file") || rc=$?
        if [[ $rc -eq 2 ]]; then error=$(jq -nc --arg e "$out" '$e'); out=""; fi
        envelope validate "$(printf '%s\n' "$out" | jq -R -s -c --arg f "$file" --argjson ok "$([[ $rc -eq 0 ]] && echo true || echo false)" --argjson err "$error" '
            {file: $f, valid: $ok, error: $err,
             violations: [split("\n")[] | select(length > 0) | . as $s
                          | (capture("^line (?<line>[0-9?]+): (\\[(?<context>[^]]+)\\] )?(?<message>.*)$")
                             // {line: "?", context: null, message: $s})
                          | {line: (if .line == "?" then null else (.line | tonumber) end),
                             context: .context, message: .message}]}')"
        return "$rc"
    fi
    lc_validate "$file" || rc=$?
    case "$rc" in
        0) echo "OK: $file is a valid LLM catalog" ;;
        1) echo "$LC_VIOLATIONS violation(s) in $file" >&2 ;;
    esac
    return "$rc"
}

# What a binding's credential is, without its value: text and JSON.
credential_of() {  # <binding-id>: sets CRED_TEXT and CRED_JSON
    local e ep mode cred lp
    if e=$(lc_get "bindings.$1" endpoint); then
        ep=$(lc_get "endpoints.$e" provider) || ep=""
        mode=$(lc_get "providers.$ep" credential_mode) || mode=""
        cred=$(lc_get "providers.$ep" credential_env) || cred=""
        if [[ "$mode" == "env" ]]; then
            if [[ "$cred" =~ $LC_ENV_NAME_RE && -n "${!cred:-}" ]]; then
                CRED_TEXT="$cred (set)"
                CRED_JSON=$(jq -nc --arg n "$cred" '{mode: "env", name: $n, set: true}')
            else
                CRED_TEXT="$cred (not set)"
                CRED_JSON=$(jq -nc --arg n "$cred" '{mode: "env", name: $n, set: false}')
            fi
        else
            CRED_TEXT="none"
            CRED_JSON=$(jq -nc --arg m "$mode" '{mode: $m, name: null, set: null}')
        fi
    else
        lp=$(lc_get "llms.$(lc_get "bindings.$1" llm)" provider) || lp=""
        mode=$(lc_get "providers.$lp" credential_mode) || mode="native"
        CRED_TEXT="its own login"
        CRED_JSON=$(jq -nc --arg m "$mode" '{mode: $m, name: null, set: null}')
    fi
}

# The target a binding is reached by: <llm> while it is the llm's one
# binding for its harness, else <llm>@<binding>.
target_of() {  # <llm> <binding> <harness>
    if lc_resolve "$3" "$1" && [[ "$LC_R_BINDING" == "$2" ]]; then printf '%s' "$1"; else printf '%s@%s' "$1" "$2"; fi
}

# One row per binding, and one for an llm nothing binds.
_row() {  # target harness model endpoint credential state
    ROWS="${ROWS}$1${CT_US}$2${CT_US}$3${CT_US}$4${CT_US}$5${CT_US}$6"$'\n'
}

cmd_list() {
    local json="$1" l b bl h model target endpoint state n rc=0 jrows='[]'
    load_catalog list "$json" || return $?

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
            target=$(target_of "$l" "$b" "$h")
            lr_resolve "$h" "$target" || true
            endpoint="-"
            if lc_get "bindings.$b" endpoint >/dev/null; then
                endpoint="${LR_ORIGIN:-endpoint $LR_ENDPOINT_ID}"
            fi
            credential_of "$b"
            state="$LR_STATE"
            if [[ -n "$LR_REASON" ]]; then state="$state: $LR_REASON"; fi
            _row "$target" "$h" "$model" "$endpoint" "$CRED_TEXT" "$state"
            jrows=$(jq -c --arg t "$target" --arg l "$l" --arg b "$b" --arg h "$h" --arg m "$model" \
                --argjson e "$(null_if_empty "$LR_ORIGIN")" --argjson c "$CRED_JSON" \
                --arg s "$LR_STATE" --argjson r "$(null_if_empty "$LR_REASON")" \
                '. + [{target: $t, llm: $l, binding: $b, harness: $h, model: $m, endpoint: $e,
                       credential: $c, state: $s, reason: $r}]' <<< "$jrows")
        done <<< "$(lc_ids bindings)"
        if [[ $n -eq 0 ]]; then
            _row "$l" "-" "$model" "-" "-" "no binding: add a [bindings.<id>] table for it"
            jrows=$(jq -c --arg l "$l" --arg m "$model" \
                '. + [{target: $l, llm: $l, binding: null, harness: null, model: $m, endpoint: null,
                       credential: null, state: null, reason: "no binding: add a [bindings.<id>] table for it"}]' <<< "$jrows")
        fi
    done <<< "$(lc_ids llms)"

    if [[ "$json" == 1 ]]; then
        envelope list "$(jq -nc --arg f "$CATALOG" --argjson t "$jrows" '{catalog: $f, targets: $t}')"
        return 0
    fi
    if [[ -z "$ROWS" ]]; then
        echo "The catalog at $CATALOG defines no llm."
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

cmd_show() {
    local id="$1" json="$2" lp kind display model b bl h target state msg n=0 jb='[]' text=""
    load_catalog show "$json" || return $?
    if ! lc_has "llms.$id"; then
        msg="unknown llm '$id' (cct llm list shows the catalog)"
        if [[ "$json" == 1 ]]; then json_error show "$msg"; else echo "cct llm: $msg" >&2; fi
        return 2
    fi
    lp=$(lc_get "llms.$id" provider) || lp=""
    kind=$(lc_get "providers.$lp" kind) || kind=""
    display=$(lc_get "providers.$lp" display_name) || display="$lp"
    model=$(lc_get "llms.$id" model) || model=""
    while IFS= read -r b; do
        [[ -z "$b" ]] && continue
        bl=$(lc_get "bindings.$b" llm) || bl=""
        [[ "$bl" == "$id" ]] || continue
        n=$((n + 1))
        h=$(lc_get "bindings.$b" harness) || h=""
        target=$(target_of "$id" "$b" "$h")
        lr_resolve "$h" "$target" || true
        lr_digests || true
        credential_of "$b"
        state="$LR_STATE"
        if [[ -n "$LR_REASON" ]]; then state="$state: $LR_REASON"; fi
        text="${text}    $target  $h  ${LR_ORIGIN:--}${LR_PROTOCOL:+, $LR_PROTOCOL}  $CRED_TEXT  $state"$'\n'
        jb=$(jq -c --arg b "$b" --arg t "$target" --arg h "$h" \
            --argjson e "$(null_if_empty "$LR_ORIGIN")" --argjson p "$(null_if_empty "$LR_PROTOCOL")" \
            --argjson c "$CRED_JSON" --arg s "$LR_STATE" --argjson r "$(null_if_empty "$LR_REASON")" \
            --arg dc "$LR_DIGEST_CATALOG" --arg dl "$LR_DIGEST_LAUNCH" --arg dopt "$LR_DIGEST_OPTIONS" \
            '. + [{id: $b, target: $t, harness: $h, endpoint: $e, protocol: $p, credential: $c,
                   state: $s, reason: $r, digests: {catalog: $dc, launch_identity: $dl, options: $dopt}}]' <<< "$jb")
    done <<< "$(lc_ids bindings)"

    if [[ "$json" == 1 ]]; then
        envelope show "$(jq -nc --arg f "$CATALOG" --arg id "$id" --arg p "$lp" --arg k "$kind" --arg d "$display" \
            --arg m "$model" --argjson cw "$(_lr_value_json "llms.$id" context_window)" \
            --argjson rs "$(_lr_value_json "llms.$id" reasoning)" --argjson in "$(_lr_value_json "llms.$id" input)" \
            --argjson b "$jb" \
            '{catalog: $f, llm: {id: $id, provider: $p, provider_kind: $k, display_name: $d, model: $m,
                                 context_window: $cw, reasoning: $rs, input: $in}, bindings: $b}')"
        return 0
    fi
    echo "llm       $id"
    echo "provider  $display ($lp, $kind)"
    echo "model     $model"
    if [[ $n -eq 0 ]]; then
        echo "bindings  none: add a [bindings.<id>] table for it"
    else
        echo "bindings  (target, harness, endpoint, credential, state)"
        printf '%s' "$text"
    fi
    return 0
}

cmd_explain() {
    local h="$1" t="$2" json="$3" rc=0 rec name kind payload line
    load_catalog explain "$json" || return $?
    lr_resolve "$h" "$t" || rc=1
    if [[ "$json" == 1 ]]; then
        envelope explain "$(lr_plan_json)"
    elif [[ $rc -ne 0 ]]; then
        echo "--llm $t on $h would be refused: $LR_REFUSAL"
    else
        echo "--llm $t on $h"
        echo "  binding   $LR_LLM@$LR_BINDING"
        echo "  provider  $(lc_get "providers.$LR_PROVIDER" display_name || printf '%s' "$LR_PROVIDER") ($LR_PROVIDER, $LR_PROVIDER_KIND)"
        if [[ -n "$LR_ENDPOINT_ID" ]]; then
            echo "  endpoint  ${LR_ORIGIN:-endpoint $LR_ENDPOINT_ID}, $LR_PROTOCOL"
        else
            echo "  endpoint  none: Claude Code's own login"
        fi
        echo "  model     $LR_MODEL"
        if [[ "$LR_STATE" == "unverified" ]]; then
            echo "  state     unverified: launchable; nothing has probed this model on $h yet"
        else
            echo "  state     $LR_STATE: $LR_REASON"
        fi
        echo "  sets      (names only; a value is read by the launch alone)"
        while IFS= read -r rec; do
            [[ -z "$rec" ]] && continue
            name="${rec%%"$CT_US"*}"; rec="${rec#*"$CT_US"}"
            kind="${rec%%"$CT_US"*}"; payload="${rec#*"$CT_US"}"
            if [[ "$kind" == "env" ]]; then
                if [[ "$payload" =~ $LC_ENV_NAME_RE && -n "${!payload:-}" ]]; then
                    echo "    $name, from $payload (set)"
                else
                    echo "    $name, from $payload (not set)"
                fi
            else
                echo "    $name"
            fi
        done <<< "$LLM_CC_ASSIGN"
        echo "  removes"
        printf '%s\n' $LLM_CC_CLEAR | awk 'NF && !seen[$0]++' | while IFS= read -r line; do echo "    $line"; done
        lr_digests
        echo "  digests   catalog ${LR_DIGEST_CATALOG:0:12}  launch identity ${LR_DIGEST_LAUNCH:0:12}  options ${LR_DIGEST_OPTIONS:0:12}"
    fi
    if [[ $rc -ne 0 || "$LR_STATE" != "unverified" ]]; then return "$EXIT_REFUSED"; fi
    return 0
}

# --json may come anywhere among a command's arguments.
JSON=0
ARGS=()
for a in "$@"; do
    if [[ "$a" == "--json" ]]; then JSON=1; else ARGS+=("$a"); fi
done
set -- ${ARGS[@]+"${ARGS[@]}"}

cmd="${1:-help}"
[[ $# -gt 0 ]] && shift
case "$cmd" in
    list)
        if [[ $# -gt 0 ]]; then echo "cct llm list takes no arguments" >&2; exit 2; fi
        cmd_list "$JSON"
        ;;
    show)
        if [[ $# -ne 1 ]]; then echo "usage: cct llm show <llm> [--json]" >&2; exit 2; fi
        cmd_show "$1" "$JSON"
        ;;
    validate)
        if [[ $# -gt 1 ]]; then echo "cct llm validate takes at most one file" >&2; exit 2; fi
        cmd_validate "${1:-}" "$JSON"
        ;;
    harness)
        # `cct harness explain <harness> --llm <target>`, dispatched here by scripts/cct.
        sub="${1:-}"; [[ $# -gt 0 ]] && shift
        if [[ "$sub" != "explain" ]]; then
            echo "usage: cct harness explain <harness> --llm <target> [--json]" >&2; exit 2
        fi
        h="" t=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --llm)   t="${2:-}"; shift; [[ $# -gt 0 ]] && shift ;;
                --llm=*) t="${1#*=}"; shift ;;
                -*)      echo "cct harness explain: unknown option '$1'" >&2; exit 2 ;;
                *)       if [[ -z "$h" ]]; then h="$1"; shift; else echo "cct harness explain: one harness" >&2; exit 2; fi ;;
            esac
        done
        if [[ -z "$h" || -z "$t" ]]; then
            echo "usage: cct harness explain <harness> --llm <target> [--json]" >&2; exit 2
        fi
        cmd_explain "$h" "$t" "$JSON"
        ;;
    help|-h|--help) usage ;;
    *) echo "cct llm: unknown command '$cmd' (list | show | validate)" >&2; usage >&2; exit 2 ;;
esac
