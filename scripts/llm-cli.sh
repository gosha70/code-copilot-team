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
#   cct llm compatibility [<target>] [--harness <h>] [--json]
#                                      each target's state (supported,
#                                      unverified, unavailable, unsupported,
#                                      incompatible) and the evidence for it
#   cct llm sessions [--harness <h>] [--project <dir>] [--json]
#                                      the --llm sessions, from the stamps
#                                      written when they started: target,
#                                      model, state, project, and whether
#                                      each can be resumed now (#400 S4)
#   cct llm test <target> [--harness <h>] [--without-guard] [--json]
#                                      run the harness on the target once,
#                                      on a canary, and record what each
#                                      capability did (#400 FR-15, S3);
#                                      refused when the harness's hooks
#                                      are off, unless --without-guard
#   cct harness explain <harness> --llm <target> [--project <dir>] [--json]
#                                      the launch plan: what a launch from
#                                      that project (default: here) would
#                                      set and remove, by name, its digests,
#                                      and why it would be refused, the
#                                      project's [llm] allow-list included
#
# Only `test` starts a harness, through the plan a launch would use, and
# its credential goes to the harness alone. Nothing else here starts a
# harness or reads a credential's value: a credential is reported by its
# variable's NAME and whether it is set, and an endpoint by its origin
# (scheme://host[:port]) alone. A target is planned by the
# resolver the launcher uses (lib/llm-resolve.sh), so an explanation and a
# launch cannot disagree. `--json` output is described by
# shared/schemas/llm-catalog-cli.schema.json. A command that cannot answer
# (a usage error, no catalog, a catalog with violations, an llm the catalog
# does not define, a rule table that cannot be read, a target that does not
# resolve) prints under --json the envelope with an error field, alone, and
# exits as its text form does.
#
# Exit codes: 0 ok; 1 the catalog has violations, or `test` ran and the
# target did not pass; 2 usage, no readable catalog, a compatibility record
# that cannot be read (named), or a probe that could not run or be recorded;
# 3 `explain` of a launch that would be refused, or `test` of a target a
# launch would refuse.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/llm-catalog.sh
source "$SCRIPT_DIR/lib/llm-catalog.sh"
# shellcheck source=lib/llm-adapters/claude-code.sh
source "$SCRIPT_DIR/lib/llm-adapters/claude-code.sh"
# shellcheck source=lib/llm-resolve.sh
source "$SCRIPT_DIR/lib/llm-resolve.sh"
# shellcheck source=lib/cct-statefile.sh
source "$SCRIPT_DIR/lib/cct-statefile.sh"
# shellcheck source=lib/llm-compat.sh
source "$SCRIPT_DIR/lib/llm-compat.sh"
# shellcheck source=lib/llm-sessions.sh
source "$SCRIPT_DIR/lib/llm-sessions.sh"
# shellcheck source=lib/llm-probe.sh
source "$SCRIPT_DIR/lib/llm-probe.sh"

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
  cct llm compatibility [<target>] [--harness <h>] [--json]
                                    each target's state and the evidence for
                                    it, from the catalog, the rule table and
                                    the test records; a target alone means
                                    its claude-code binding
  cct llm sessions [--harness <h>] [--project <dir>] [--json]
                                    the --llm sessions, stamped when they
                                    started: target, model, state, project,
                                    and whether each can be resumed now
  cct llm test <target> [--harness <h>] [--without-guard] [--json]
                                    run the harness on the target once, on a
                                    canary, and record what each capability
                                    did; a --llm launch needs a passing test.
                                    Refused when the harness's hooks are off,
                                    since the test's guard is one; then
                                    --without-guard runs it unguarded
  cct harness explain <harness> --llm <target> [--project <dir>] [--json]
                                    what a launch from that project (default:
                                    here) would set and remove, by name, and
                                    why it would be refused

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

# A usage error: the message on stderr, or under --json the error envelope
# alone, with no catalog (none was read) and a null command when none was
# recognized. Exits 2.
usage_error() {  # <command, or "" when none was recognized> <message>
    if [[ "$JSON" == 1 ]]; then
        jq -nc --argjson v "$LR_PLAN_SCHEMA_VERSION" --arg c "$1" --arg e "$2" \
            '{schema_version: $v, command: (if $c == "" then null else $c end), error: $e}'
    else
        echo "$2" >&2
    fi
    exit 2
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

_print_rows() {  # [header]: ROWS in six columns, under cct llm list's header by default
    local header="${1:-TARGET${CT_US}HARNESS${CT_US}MODEL${CT_US}ENDPOINT${CT_US}CREDENTIAL${CT_US}STATE}"
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
        if [[ "$json" == 1 ]]; then lr_digests || true; fi  # only the JSON form shows them
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

cmd_explain() {  # <harness> <target> <json> <project-dir>
    local h="$1" t="$2" json="$3" project="$4" rc=0 rec name kind payload line
    load_catalog explain "$json" || return $?
    lr_resolve "$h" "$t" "$project" || rc=1
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

# Each target's state and the evidence for it (FR-13, FR-16): every binding
# in catalog order, those of one harness, or one target.
cmd_compatibility() {  # <target or empty> <harness or empty> <json>
    local target="$1" only="$2" json="$3" l b bl h t rc worst=0 pairs="" rec
    local jrows='[]' rows="" w1=6 w2=7 w3=5 f1 f2 f3 f4 rest hv=""
    load_catalog compatibility "$json" || return $?
    if ! lcm_load_rules; then
        if [[ "$json" == 1 ]]; then json_error compatibility "$LCM_ERR"; else echo "cct llm: $LCM_ERR" >&2; fi
        return 2
    fi
    if [[ -n "$target" ]]; then
        pairs="${only:-$LLM_CC_HARNESS}${CT_US}$target"$'\n'
    else
        while IFS= read -r l; do
            [[ -z "$l" ]] && continue
            while IFS= read -r b; do
                [[ -z "$b" ]] && continue
                bl=$(lc_get "bindings.$b" llm) || bl=""
                [[ "$bl" == "$l" ]] || continue
                h=$(lc_get "bindings.$b" harness) || h=""
                [[ -z "$only" || "$h" == "$only" ]] || continue
                pairs="$pairs$h${CT_US}$(target_of "$l" "$b" "$h")"$'\n'
            done <<< "$(lc_ids bindings)"
        done <<< "$(lc_ids llms)"
    fi

    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        h="${rec%%"$CT_US"*}"; t="${rec#*"$CT_US"}"
        rc=0; lcm_state "$h" "$t" || rc=$?
        if [[ "$rc" -eq 1 ]]; then
            if [[ "$json" == 1 ]]; then json_error compatibility "$LCM_ERR"; else echo "cct llm compatibility: $LCM_ERR" >&2; fi
            return 2
        fi
        if [[ "$rc" -eq 2 ]]; then
            worst=2
            echo "cct llm compatibility: $LCM_ERR" >&2
        fi
        [[ -n "$LCM_HV" ]] && hv="$LCM_EXE $LCM_HV"
        rows="${rows}$t${CT_US}$h${CT_US}$LCM_STATE${CT_US}$LCM_REASON"$'\n'
        [[ ${#t} -gt $w1 ]] && w1=${#t}
        [[ ${#h} -gt $w2 ]] && w2=${#h}
        [[ ${#LCM_STATE} -gt $w3 ]] && w3=${#LCM_STATE}
        jrows=$(jq -c --arg t "$t" --arg l "$LR_LLM" --arg b "$LR_BINDING" --arg h "$h" \
            --arg s "$LCM_STATE" --arg r "$LCM_REASON" --argjson d "$LCM_DEGRADED" \
            --argjson e "$LCM_EVIDENCE" --argjson rec "${LCM_RECORD:-null}" '
            def brief: if . == null then null else {at, outcome} end;
            . + [{target: $t, llm: $l, binding: $b, harness: $h, state: $s, reason: $r,
                  degraded: $d, evidence: $e,
                  latest_attempt: ($rec.latest_attempt // null | brief),
                  latest_conclusive: ($rec.latest_conclusive // null | brief)}]' <<< "$jrows")
    done <<< "$pairs"

    if [[ "$json" == 1 ]]; then
        envelope compatibility "$(jq -nc --arg f "$CATALOG" --argjson rv "$(lcm_rule_version)" --argjson t "$jrows" \
            '{catalog: $f, rule_version: $rv, targets: $t}')"
        return "$worst"
    fi
    if [[ -z "$rows" ]]; then
        echo "The catalog at $CATALOG has no binding${only:+ for $only}."
        return "$worst"
    fi
    printf "%-${w1}s  %-${w2}s  %-${w3}s  %s\n" "TARGET" "HARNESS" "STATE" "WHY"
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        f1="${rec%%"$CT_US"*}"; rest="${rec#*"$CT_US"}"
        f2="${rest%%"$CT_US"*}"; rest="${rest#*"$CT_US"}"
        f3="${rest%%"$CT_US"*}"; f4="${rest#*"$CT_US"}"
        printf "%-${w1}s  %-${w2}s  %-${w3}s  %s\n" "$f1" "$f2" "$f3" "$f4"
    done <<< "$rows"
    echo ""
    echo "Rule version $(lcm_rule_version)${hv:+; $hv}. Computed from the catalog, the rule table and the test records; nothing was sent anywhere."
    return "$worst"
}

# The stamps of --llm sessions (#400 FR-6, FR-17, S4), newest first: one
# harness's, and only one project's when it is given. A stamp is promoted to
# established, with the effective model, from the harness's own transcript
# for that session. Whether each can be resumed now is the check a resume by
# its id makes (FR-18, FR-19), in the launcher's order: a valid catalog; its
# stamped target resolving, for its project, to a launchable binding; no
# settings file setting a variable the launch controls; the launch identity
# it was stamped with; a compatibility state that can be computed, which the
# stamp's refresh needs, and that the gate admits without --allow-unverified
# (supported; S3).
cmd_sessions() {  # <json> <harness> <project, physical, or empty for all>
    local json="$1" h="$2" only="$3" dir f id rc worst=0 catalog_err="" eligible reason t project jrows='[]'
    dir=$(lss_dir "$h")
    CATALOG="$(lc_catalog_path)"
    if [[ ! -e "$CATALOG" ]]; then
        catalog_err="there is no LLM catalog at $CATALOG"
    elif ! lc_validate "$CATALOG" >/dev/null 2>&1; then
        catalog_err="the LLM catalog is not valid (cct llm validate): $CATALOG"
    fi
    for f in "$dir"/*.json; do
        id=$(basename "$f" .json)
        [[ "$id" =~ $LSS_UUID_RE ]] || continue   # a stamp is named by its session id
        rc=0; lss_read "$h" "$id" || rc=$?
        [[ "$rc" -eq 1 ]] && continue   # removed since the directory was listed
        if [[ "$rc" -ne 0 ]]; then
            echo "cct llm sessions: $LSS_ERR" >&2
            worst=2
            continue
        fi
        project=$(jq -r '.project // ""' <<< "$LSS_STAMP")
        [[ -z "$only" || "$project" == "$only" ]] || continue
        if lss_promote "$h" "$id"; then lss_read "$h" "$id" || true; fi
        t="$LSS_STAMP_TARGET"
        eligible=false reason=""
        if [[ -n "$catalog_err" ]]; then
            reason="$catalog_err"
        elif ! lr_resolve "$h" "$t" "$project"; then
            reason="$LR_REFUSAL"
        elif [[ "$LR_STATE" != "unverified" ]]; then
            reason="$t is $LR_STATE on $h: $LR_REASON"
        else
            rc=0; llm_cc_settings_conflicts "$project" || rc=$?
            lr_digests || true
            if [[ "$rc" -eq 1 ]]; then
                reason="a Claude Code settings file sets a variable this launch must control ($(head -1 <<< "$LLM_CC_SETTINGS_REFUSED"))"
            elif [[ "$LR_DIGEST_LAUNCH" != "$(jq -r '.digests.launch_identity // ""' <<< "$LSS_STAMP")" ]]; then
                reason="the launch identity of $t changed since the session was stamped (its provider, endpoint, protocol, auth header, model, credential or quirks)"
            elif ! lcm_state "$h" "$t"; then
                reason="the compatibility state of $t cannot be computed: ${LCM_ERR:-unknown}"
            else
                case "$LCM_STATE" in   # the launcher's gate (S3)
                    supported)  eligible=true ;;
                    unverified) reason="$t has not passed a test on $h: $LCM_REASON (cct llm test $t; or resume with --allow-unverified)" ;;
                    *)          reason="$t is $LCM_STATE on $h: $LCM_REASON" ;;
                esac
            fi
        fi
        jrows=$(jq -c --argjson s "$LSS_STAMP" --arg id "$id" --arg h "$h" --arg t "$t" \
            --argjson e "$eligible" --argjson r "$(null_if_empty "$reason")" '
            . + [$s | {session_id: $id, harness: $h, target: $t, llm, binding, requested_model,
                       effective_model, status, project, forked_from, created_at, refreshed_at,
                       established_at, resume: {eligible: $e, reason: $r}}]' <<< "$jrows")
    done
    jrows=$(jq -c 'sort_by(.refreshed_at) | reverse' <<< "$jrows")
    if [[ "$json" == 1 ]]; then
        envelope sessions "$(jq -nc --arg h "$h" --arg d "$dir" --argjson s "$jrows" \
            '{harness: $h, sessions_dir: $d, sessions: $s}')"
        return "$worst"
    fi
    if [[ "$(jq length <<< "$jrows")" -eq 0 ]]; then
        echo "No $h session started with --llm${only:+ in $only} has a stamp yet ($dir)."
        return "$worst"
    fi
    echo "$h sessions started with --llm${only:+ in $only}, newest first (stamps: $dir)"
    ROWS=$(jq -r --arg us "$CT_US" '.[] | [.session_id, .target, (.effective_model // .requested_model // "-"),
        (.status // "-"), (if .resume.eligible then "yes" else "no" end), (.project // "-")] | join($us)' <<< "$jrows")
    _print_rows "SESSION${CT_US}TARGET${CT_US}MODEL${CT_US}STATUS${CT_US}RESUME${CT_US}PROJECT"
    if jq -e 'any(.[]; .resume.eligible | not)' >/dev/null <<< "$jrows"; then
        echo ""
        jq -r '.[] | select(.resume.eligible | not) | "Not resumable now: \(.session_id): \(.resume.reason)"' <<< "$jrows"
    fi
    echo ""
    echo "Resume one by its id, on the target it was started with: claude-code --resume <session>"
    return "$worst"
}

# One behavioral test of a target on a harness (#400 FR-15, S3): the harness
# runs headless on the canary, with the environment a launch of the target
# gets, and its per-capability matrix is recorded (FR-16). A target a launch
# would refuse (unsupported, unavailable) is refused the same way, and
# nothing runs. Interrupted, the harness's process group is reaped and the
# probe's private directory removed.
cmd_test() {  # <target> <harness> <json> <without-guard>
    local target="$1" h="$2" json="$3" without_guard="${4:-0}" rc=0 c
    load_catalog test "$json" || return $?
    if ! lcm_load_rules; then
        if [[ "$json" == 1 ]]; then json_error test "$LCM_ERR"; else echo "cct llm: $LCM_ERR" >&2; fi
        return 2
    fi
    # The guard is a Claude Code hook: with hooks off, the endpoint under test
    # could run whatever the user's permission rules allow, as the real binary
    # was seen to. That refuses the test, naming the cause, before anything
    # runs, unless --without-guard asks for an unguarded run.
    lp_hooks_off
    if [[ -n "$LP_HOOKS_OFF" && "$without_guard" != 1 ]]; then
        c="hooks are off for this test ($LP_HOOKS_OFF), and with them the guard that stops the endpoint under test from running anything but this test's command"
        if [[ "$json" == 1 ]]; then
            json_error test "refused: $c; turn hooks back on, or pass --without-guard to run it unguarded"
        else
            echo "cct llm test: refused: $c." >&2
            echo "  Turn hooks back on, or pass --without-guard to run the test unguarded." >&2
        fi
        return "$EXIT_REFUSED"
    fi
    CA_OWNER_ID="$$"
    if ! CA_ACTIVE_GROUP_FILE=$(mktemp "${TMPDIR:-/tmp}/cct-llm-test-group.XXXXXX"); then
        c="cannot create the probe's handoff record, so a signal could not stop it; refusing to run"
        if [[ "$json" == 1 ]]; then json_error test "$c"; else echo "cct llm test: $c" >&2; fi
        return 2
    fi
    export CA_OWNER_ID CA_ACTIVE_GROUP_FILE
    trap 'lp_cleanup; rm -f "$CA_ACTIVE_GROUP_FILE"; exit 130' INT
    trap 'lp_cleanup; rm -f "$CA_ACTIVE_GROUP_FILE"; exit 143' TERM
    trap 'lp_cleanup; rm -f "$CA_ACTIVE_GROUP_FILE"; exit 129' HUP
    trap 'lp_cleanup; rm -f "$CA_ACTIVE_GROUP_FILE"' EXIT
    [[ "$json" == 1 ]] || echo "Testing $target on $h (up to ${CCT_LLM_PROBE_TIMEOUT_SEC:-$LP_TIMEOUT_DEFAULT_SEC}s)..." >&2
    if [[ -n "${CCT_LLM_PROBE_CMD:-}" ]]; then
        echo "cct llm test: note: CCT_LLM_PROBE_CMD is set, so it runs in place of $LLM_CC_EXECUTABLE, and the run is recorded as unverifiable: it decides nothing." >&2
    fi
    if [[ -n "$LP_HOOKS_OFF" ]]; then
        echo "cct llm test: warning: --without-guard: hooks are off for this test ($LP_HOOKS_OFF), and with them the guard that stops the endpoint under test from running anything but this test's command: your permission rules alone decide what it may run. The test still fails if it asks for more." >&2
    fi
    lp_probe "$h" "$target" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        if [[ "$LP_REFUSED" == 1 ]]; then
            if [[ "$json" == 1 ]]; then
                json_error test "refused: $LP_ERR"
            else
                echo "cct llm test: refused: $LP_ERR" >&2
                echo "  A launch would be refused for the same reason; fix it, then test again." >&2
            fi
            return "$EXIT_REFUSED"
        fi
        if [[ "$json" == 1 ]]; then json_error test "$LP_ERR"; else echo "cct llm test: $LP_ERR" >&2; fi
        return 2
    fi
    # Tuning in a settings file does not change the target: said, as for a
    # launch; that value is the one the test ran with.
    while IFS= read -r c; do
        [[ -z "$c" ]] && continue
        echo "cct llm test: note: ${c%: *} sets ${c##*: } in its env block; Claude Code applies it over this test, so that value is the one tested." >&2
    done <<< "$LP_NOTES"
    # The state the records now give, the one just written included.
    rc=0; lcm_state "$h" "$target" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        if [[ "$json" == 1 ]]; then json_error test "$LCM_ERR"; else echo "cct llm test: $LCM_ERR" >&2; fi
        return 2
    fi
    if [[ "$json" == 1 ]]; then
        envelope test "$(jq -nc --arg f "$CATALOG" --arg t "$target" --arg l "$LR_LLM" --arg b "$LR_BINDING" \
            --arg h "$h" --arg o "$LP_OUTCOME" --arg d "$LP_DETAIL" --argjson m "$LP_MATRIX" \
            --arg s "$LCM_STATE" --arg r "$LCM_REASON" --argjson e "$LCM_EVIDENCE" \
            '{catalog: $f, target: $t, llm: $l, binding: $b, harness: $h, outcome: $o, detail: $d,
              matrix: $m, state: $s, reason: $r, evidence: $e}')"
    else
        echo "Tested $target on $h: $LLM_CC_LABEL"
        echo ""
        printf "%-18s  %s\n" "CAPABILITY" "RESULT"
        jq -r 'to_entries[] | "\(.key)\t\(.value)"' <<< "$LP_MATRIX" | while IFS=$'\t' read -r cap res; do
            printf "%-18s  %s\n" "$cap" "$res"
        done
        echo ""
        echo "Outcome: $LP_OUTCOME: $LP_DETAIL"
        echo "State: $LCM_STATE ($LCM_REASON)"
    fi
    [[ "$LP_OUTCOME" == "pass" ]]
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
        if [[ $# -gt 0 ]]; then usage_error list "cct llm list takes no arguments"; fi
        cmd_list "$JSON"
        ;;
    show)
        if [[ $# -ne 1 ]]; then usage_error show "usage: cct llm show <llm> [--json]"; fi
        cmd_show "$1" "$JSON"
        ;;
    validate)
        if [[ $# -gt 1 ]]; then usage_error validate "cct llm validate takes at most one file"; fi
        cmd_validate "${1:-}" "$JSON"
        ;;
    compatibility)
        t="" h=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --harness)   h="${2:-}"; [[ -n "$h" ]] || usage_error compatibility "cct llm compatibility: --harness needs a harness"; shift 2 ;;
                --harness=*) h="${1#*=}"; [[ -n "$h" ]] || usage_error compatibility "cct llm compatibility: --harness needs a harness"; shift ;;
                -*)          usage_error compatibility "cct llm compatibility: unknown option '$1'" ;;
                *)           if [[ -z "$t" ]]; then t="$1"; shift; else usage_error compatibility "cct llm compatibility: one target"; fi ;;
            esac
        done
        if [[ -n "$h" && " $LC_HARNESSES " != *" $h "* ]]; then
            usage_error compatibility "cct llm compatibility: unknown harness '$h' (one of: ${LC_HARNESSES// /, })"
        fi
        cmd_compatibility "$t" "$h" "$JSON"
        ;;
    sessions)
        h="$LLM_CC_HARNESS" p=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --harness)   h="${2:-}"; [[ -n "$h" ]] || usage_error sessions "cct llm sessions: --harness needs a harness"; shift 2 ;;
                --harness=*) h="${1#*=}"; [[ -n "$h" ]] || usage_error sessions "cct llm sessions: --harness needs a harness"; shift ;;
                --project)   p="${2:-}"; [[ -n "$p" ]] || usage_error sessions "cct llm sessions: --project needs a directory"; shift 2 ;;
                --project=*) p="${1#*=}"; [[ -n "$p" ]] || usage_error sessions "cct llm sessions: --project needs a directory"; shift ;;
                *)           usage_error sessions "cct llm sessions: unknown argument '$1'" ;;
            esac
        done
        if [[ " $LC_HARNESSES " != *" $h "* ]]; then
            usage_error sessions "cct llm sessions: unknown harness '$h' (one of: ${LC_HARNESSES// /, })"
        fi
        if [[ -n "$p" ]]; then
            [[ -d "$p" ]] || usage_error sessions "cct llm sessions: no such directory: $p"
            p=$(cd "$p" && pwd -P)
        fi
        cmd_sessions "$JSON" "$h" "$p"
        ;;
    test)
        t="" h="$LLM_CC_HARNESS" wg=0
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --harness)   h="${2:-}"; [[ -n "$h" ]] || usage_error test "cct llm test: --harness needs a harness"; shift 2 ;;
                --harness=*) h="${1#*=}"; [[ -n "$h" ]] || usage_error test "cct llm test: --harness needs a harness"; shift ;;
                --without-guard) wg=1; shift ;;
                -*)          usage_error test "cct llm test: unknown option '$1'" ;;
                *)           if [[ -z "$t" ]]; then t="$1"; shift; else usage_error test "cct llm test: one target"; fi ;;
            esac
        done
        [[ -n "$t" ]] || usage_error test "usage: cct llm test <target> [--harness <h>] [--without-guard] [--json]"
        if [[ " $LC_HARNESSES " != *" $h "* ]]; then
            usage_error test "cct llm test: unknown harness '$h' (one of: ${LC_HARNESSES// /, })"
        fi
        cmd_test "$t" "$h" "$JSON" "$wg"
        ;;
    harness)
        # `cct harness explain <harness> --llm <target>`, dispatched here by scripts/cct.
        sub="${1:-}"; [[ $# -gt 0 ]] && shift
        if [[ "$sub" != "explain" ]]; then
            usage_error "" "usage: cct harness explain <harness> --llm <target> [--project <dir>] [--json]"
        fi
        h="" t="" p="."
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --llm)       t="${2:-}"; shift; [[ $# -gt 0 ]] && shift ;;
                --llm=*)     t="${1#*=}"; shift ;;
                --project)   p="${2:-}"; [[ -n "$p" ]] || usage_error explain "cct harness explain: --project needs a directory"; shift 2 ;;
                --project=*) p="${1#*=}"; [[ -n "$p" ]] || usage_error explain "cct harness explain: --project needs a directory"; shift ;;
                -*)          usage_error explain "cct harness explain: unknown option '$1'" ;;
                *)           if [[ -z "$h" ]]; then h="$1"; shift; else usage_error explain "cct harness explain: one harness"; fi ;;
            esac
        done
        if [[ -z "$h" || -z "$t" ]]; then
            usage_error explain "usage: cct harness explain <harness> --llm <target> [--project <dir>] [--json]"
        fi
        if [[ ! -d "$p" ]]; then
            usage_error explain "cct harness explain: no such directory: $p"
        fi
        cmd_explain "$h" "$t" "$JSON" "$p"
        ;;
    help|-h|--help) usage ;;
    *)
        msg="cct llm: unknown command '$cmd' (list | show | validate | compatibility | sessions | test)"
        if [[ "$JSON" == 1 ]]; then usage_error "" "$msg"; fi
        echo "$msg" >&2; usage >&2; exit 2
        ;;
esac
