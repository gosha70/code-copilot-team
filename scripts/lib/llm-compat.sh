#!/usr/bin/env bash
# llm-compat.sh — whether a catalog target works on a harness (#400 FR-13,
# FR-14, FR-16; slice S2). The five states, computed from the catalog, the
# rule table (shared/llm/compat-rules.json), the installed harness and the
# probe records under the user home:
#
#   unsupported   the rule table says the harness cannot speak the endpoint's
#                 protocol, honour a declared quirk, or use a managed
#                 provider; or the adapter's own static check says so
#   unavailable   a credential or base URL is missing (the adapter's check),
#                 or the harness is not installed or older than the table's
#                 minimum
#   supported     the latest conclusive record passed every capability the
#                 binding requires, under the current evidence digest
#   incompatible  the latest conclusive record failed, under the current
#                 evidence digest
#   unverified    otherwise: never tested, or tested under other evidence
#                 (the reason says what changed)
#
# The evidence digest is FR-9's: launch identity, options, harness version
# and rule version. Nothing here performs network I/O; lcm_record_attempt is
# the only writer, for the probe.
#
# Needs cct-home.sh, cct-endpoint.sh, llm-catalog.sh,
# llm-adapters/claude-code.sh, llm-resolve.sh and cct-statefile.sh sourced
# first; jq.
#
# bash 3.2 compatible.

LCM_RULES_FILE="${CCT_LLM_RULES_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/shared/llm/compat-rules.json}"
LCM_RECORDS_REL="llm-compat"
LCM_RECORD_SCHEMA_VERSION=1
LCM_RULES=""

# The shape of one attempt, as jq: what latest_attempt and latest_conclusive hold.
LCM_ATTEMPT_JQ='
  def hex64: type == "string" and test("^[0-9a-f]{64}$");
  type == "object"
  and (.at | type == "string")
  and (.outcome | IN("pass", "fail", "unverifiable"))
  and (.matrix | type == "object"
       and all(to_entries[]; .value | IN("pass", "fail", "unverifiable", "not_applicable")))
  and (.evidence | type == "object"
       and (.digest | hex64) and (.launch_identity | hex64) and (.options | hex64)
       and (.harness_version | type == "string") and (.rule_version | type == "number"))
  and ((.detail // "") | type == "string")'

lcm_load_rules() {  # -> LCM_RULES; 2 with LCM_ERR when the table is unusable
    [[ -n "$LCM_RULES" ]] && return 0
    LCM_ERR=""
    if ! LCM_RULES=$(jq -ce 'select(type == "object" and (.rule_version | type == "number")
                                    and (.harnesses | type == "object"))' "$LCM_RULES_FILE" 2>/dev/null); then
        LCM_RULES=""
        LCM_ERR="cannot read the compatibility rule table: $LCM_RULES_FILE"
        return 2
    fi
}

lcm_rule_version() { jq -r '.rule_version' <<< "$LCM_RULES"; }

_lcm_rule_list() {  # <harness> <field> -> the field's elements, one per line
    jq -r --arg h "$1" --arg f "$2" '.harnesses[$h][$f] // [] | .[]' <<< "$LCM_RULES"
}

_lcm_version_lt() {  # <a> <b>: a < b, as dotted numbers
    local a="$1" b="$2" x y
    while [[ -n "$a" || -n "$b" ]]; do
        x="${a%%.*}"; y="${b%%.*}"
        [[ "$a" == *.* ]] && a="${a#*.}" || a=""
        [[ "$b" == *.* ]] && b="${b#*.}" || b=""
        x=$((10#${x:-0})); y=$((10#${y:-0}))
        [[ "$x" -lt "$y" ]] && return 0
        [[ "$x" -gt "$y" ]] && return 1
    done
    return 1
}

# lcm_harness_version <harness> -> LCM_HV, the installed version ("unknown"
# when it prints none); 1 with LCM_HV empty when it is not installed.
lcm_harness_version() {
    local exe out
    LCM_HV=""
    case "$1" in
        "$LLM_CC_HARNESS") exe="$LLM_CC_EXECUTABLE" ;;
        *) return 1 ;;
    esac
    LCM_EXE="$exe"
    if [[ "${_LCM_HV_FOR:-}" == "$1" ]]; then   # asked once per process
        LCM_HV="$_LCM_HV_VAL"
        [[ -n "$LCM_HV" ]]
        return
    fi
    if command -v "$exe" >/dev/null 2>&1; then
        out=$("$exe" --version 2>/dev/null | head -1) || out=""
        if [[ "$out" =~ ([0-9]+\.[0-9]+\.[0-9]+) ]]; then LCM_HV="${BASH_REMATCH[1]}"; else LCM_HV="unknown"; fi
    fi
    _LCM_HV_FOR="$1"
    _LCM_HV_VAL="$LCM_HV"
    [[ -n "$LCM_HV" ]]
}

lcm_records_dir() { cct_home_path "$LCM_RECORDS_REL"; }
lcm_record_path() {  # <harness> <llm> <binding>
    printf '%s\n' "$(lcm_records_dir)/$1/$2@$3.json"
}

_lcm_record_valid() {  # <harness> <llm> <binding>, the record on stdin
    jq -e --arg h "$1" --arg l "$2" --arg b "$3" --argjson v "$LCM_RECORD_SCHEMA_VERSION" "
        def attempt: $LCM_ATTEMPT_JQ;
        type == \"object\" and .schema_version == \$v
        and .harness == \$h and .llm == \$l and .binding == \$b
        and (.latest_attempt == null or (.latest_attempt | attempt))
        and (.latest_conclusive == null
             or ((.latest_conclusive | attempt) and (.latest_conclusive.outcome | IN(\"pass\", \"fail\"))))
    " >/dev/null 2>&1
}

# lcm_record_read <harness> <llm> <binding> -> LCM_RECORD. 0 read; 1 absent;
# 2 refused, with LCM_ERR naming the file (FR-29: a malformed file is
# refused by name, never treated as absent).
lcm_record_read() {
    local path rc=0
    LCM_RECORD="" LCM_ERR=""
    path=$(lcm_record_path "$1" "$2" "$3")
    LCM_RECORD=$(sf_read "$path") || rc=$?
    if [[ "$rc" -eq 1 ]]; then LCM_RECORD=""; return 1; fi
    if [[ "$rc" -ne 0 ]]; then LCM_RECORD=""; LCM_ERR="cannot read the record $path"; return 2; fi
    if ! _lcm_record_valid "$1" "$2" "$3" <<< "$LCM_RECORD"; then
        LCM_RECORD=""
        LCM_ERR="the record $path is malformed"
        return 2
    fi
}

_lcm_merge_attempt() {  # <harness> <llm> <binding> <path> <attempt>, the current record on stdin
    local cur
    cur=$(cat)
    if [[ -n "$cur" ]] && ! _lcm_record_valid "$1" "$2" "$3" <<< "$cur"; then
        printf 'the record %s is malformed; not updated' "$4"
        return 1
    fi
    jq -n --arg h "$1" --arg l "$2" --arg b "$3" --argjson v "$LCM_RECORD_SCHEMA_VERSION" \
        --argjson a "$5" --argjson cur "${cur:-null}" '
        ($cur // {schema_version: $v, harness: $h, llm: $l, binding: $b,
                  latest_attempt: null, latest_conclusive: null})
        | .latest_attempt = $a
        | if ($a.outcome | IN("pass", "fail")) then .latest_conclusive = $a else . end'
}

# lcm_record_attempt <harness> <llm> <binding> <attempt-json>: record one
# probe run. Every run replaces latest_attempt; only a pass or a behavioral
# fail replaces latest_conclusive (FR-16).
lcm_record_attempt() {
    local path
    LCM_ERR=""
    if ! jq -e "$LCM_ATTEMPT_JQ" >/dev/null 2>&1 <<< "$4"; then
        LCM_ERR="not a probe attempt: $4"
        return 1
    fi
    path=$(lcm_record_path "$1" "$2" "$3")
    sf_dir "$(lcm_records_dir)" || { LCM_ERR="$SF_ERR"; return 1; }
    sf_update "$path" _lcm_merge_attempt "$1" "$2" "$3" "$path" "$4" || { LCM_ERR="$SF_ERR"; return 1; }
}

# The rule table's static verdict for the resolved binding (LR_*): sets
# LCM_STATE=unsupported and LCM_REASON, or leaves them empty.
_lcm_static() {  # <harness>
    local h="$1" p q
    if [[ -z "$LR_ENDPOINT_ID" ]]; then
        if [[ "$(jq -r --arg h "$h" '.harnesses[$h].managed' <<< "$LCM_RULES")" != "true" ]]; then
            LCM_STATE="unsupported"
            LCM_REASON="$h cannot use a managed provider's own login"
        fi
        return 0
    fi
    if ! _lcm_rule_list "$h" protocols | grep -qxF -- "$LR_PROTOCOL"; then
        LCM_STATE="unsupported"
        p=$(_lcm_rule_list "$h" protocols | paste -sd' ' - | sed 's/ / or /g')
        if [[ -z "$p" ]]; then
            LCM_REASON="$h reaches only its own managed models; endpoint '$LR_ENDPOINT_ID' cannot be used"
        else
            LCM_REASON="endpoint '$LR_ENDPOINT_ID' speaks $LR_PROTOCOL, $h speaks $p"
        fi
        return 0
    fi
    while IFS= read -r q; do
        [[ -z "$q" ]] && continue
        if ! _lcm_rule_list "$h" quirks | grep -qxF -- "$q"; then
            LCM_STATE="unsupported"
            LCM_REASON="$h cannot honour the quirk '$q' that endpoint '$LR_ENDPOINT_ID' declares"
            return 0
        fi
    done <<< "$(lc_array_elems "endpoints.$LR_ENDPOINT_ID" quirks 2>/dev/null)"
}

# The capabilities this binding must pass: the harness's required set, plus
# reasoning_control when the llm declares reasoning and image_input when it
# declares image input, where the harness lists them as conditional.
lcm_required() {  # <harness> <llm> -> names, one per line
    local c
    _lcm_rule_list "$1" required
    while IFS= read -r c; do
        case "$c" in
            reasoning_control)
                [[ "$(lc_get "llms.$2" reasoning 2>/dev/null)" == "true" ]] && echo "$c" ;;
            image_input)
                lc_array_elems "llms.$2" input 2>/dev/null | grep -qx image && echo "$c" ;;
        esac
    done <<< "$(_lcm_rule_list "$1" conditional)"
    return 0
}

_lcm_changed() {  # <old-evidence> <new-evidence> -> JSON array of the parts that differ
    jq -nc --argjson o "$1" --argjson n "$2" \
        '[("launch_identity", "options", "harness_version", "rule_version") as $k
          | select($o[$k] != $n[$k]) | $k]'
}

_lcm_changed_text() {  # <old-evidence> <new-evidence> -> what changed, in words
    jq -nr --argjson o "$1" --argjson n "$2" --arg exe "$LCM_EXE" '
        [ (select($o.launch_identity != $n.launch_identity) | "the launch identity changed"),
          (select($o.options != $n.options) | "the options changed"),
          (select($o.harness_version != $n.harness_version) | "\($exe) \($o.harness_version) is now \($n.harness_version)"),
          (select($o.rule_version != $n.rule_version) | "rule version \($o.rule_version) is now \($n.rule_version)") ]
        | join(", ")'
}

# lcm_state <harness> <target>: LCM_STATE, LCM_REASON, LCM_DEGRADED (a JSON
# array: what changed since the latest conclusive record), LCM_EVIDENCE
# (the current evidence as JSON, or null when the harness is not
# installed) and LCM_RECORD; the resolver's LR_* stay set.
# Returns 0; 1 when the target does not resolve (LCM_ERR says why); 2 when
# the rule table or the record is unusable (LCM_ERR names it; the state is
# still computed, without the record).
lcm_state() {
    local h="$1" conclusive outcome at changed failed missing c rv min
    LCM_STATE="" LCM_REASON="" LCM_DEGRADED="[]" LCM_EVIDENCE="null" LCM_RECORD="" LCM_ERR="" LCM_EXE=""
    lcm_load_rules || return 2
    if ! lr_resolve "$h" "$2"; then LCM_ERR="$LR_REFUSAL"; return 1; fi

    _lcm_static "$h"
    if [[ -z "$LCM_STATE" && "$LR_STATE" != "unverified" ]]; then
        LCM_STATE="$LR_STATE"
        LCM_REASON="$LR_REASON"
    fi
    if lcm_harness_version "$h"; then
        rv=$(lcm_rule_version)
        lr_digests
        LCM_EVIDENCE=$(jq -nc --arg li "$LR_DIGEST_LAUNCH" --arg o "$LR_DIGEST_OPTIONS" \
            --arg hv "$LCM_HV" --argjson rv "$rv" \
            '{launch_identity: $li, options: $o, harness_version: $hv, rule_version: $rv}')
        LCM_EVIDENCE=$(jq -c --arg d "$(jq -cS . <<< "$LCM_EVIDENCE" | _lr_sha256)" '. + {digest: $d}' <<< "$LCM_EVIDENCE")
        min=$(jq -r --arg h "$h" '.harnesses[$h].min_version // empty' <<< "$LCM_RULES")
        if [[ -z "$LCM_STATE" && -n "$min" && "$LCM_HV" != "unknown" ]] && _lcm_version_lt "$LCM_HV" "$min"; then
            LCM_STATE="unavailable"
            LCM_REASON="$LCM_EXE $LCM_HV is older than $min, the oldest version $h supports"
        fi
    elif [[ -z "$LCM_STATE" ]]; then
        LCM_STATE="unavailable"
        LCM_REASON="${LCM_EXE:-the harness} is not installed (not found on PATH)"
    fi

    if ! lcm_record_read "$h" "$LR_LLM" "$LR_BINDING"; then
        if [[ -n "$LCM_ERR" ]]; then
            [[ -n "$LCM_STATE" ]] || { LCM_STATE="unverified"; LCM_REASON="$LCM_ERR; it was not used"; }
            return 2
        fi
    fi
    [[ -n "$LCM_STATE" ]] && return 0

    conclusive=$(jq -c '.latest_conclusive // null' <<< "${LCM_RECORD:-null}")
    if [[ "$conclusive" == "null" ]]; then
        LCM_STATE="unverified"
        outcome=$(jq -r '.latest_attempt.outcome // empty' <<< "${LCM_RECORD:-null}")
        at=$(jq -r '.latest_attempt.at // empty' <<< "${LCM_RECORD:-null}")
        if [[ -n "$outcome" ]]; then
            LCM_REASON="never tested conclusively: the last test, $at, was $outcome"
        else
            LCM_REASON="never tested"
        fi
        return 0
    fi
    outcome=$(jq -r '.outcome' <<< "$conclusive")
    at=$(jq -r '.at' <<< "$conclusive")
    if [[ "$(jq -r '.evidence.digest' <<< "$conclusive")" != "$(jq -r '.digest' <<< "$LCM_EVIDENCE")" ]]; then
        LCM_STATE="unverified"
        LCM_DEGRADED=$(_lcm_changed "$(jq -c '.evidence' <<< "$conclusive")" "$LCM_EVIDENCE")
        changed=$(_lcm_changed_text "$(jq -c '.evidence' <<< "$conclusive")" "$LCM_EVIDENCE")
        LCM_REASON="the test of $at ($outcome) no longer applies: ${changed:-its evidence differs}"
        return 0
    fi
    if [[ "$outcome" == "fail" ]]; then
        failed=$(jq -r '[.matrix | to_entries[] | select(.value == "fail") | .key] | join(", ")' <<< "$conclusive")
        LCM_STATE="incompatible"
        LCM_REASON="failed its test of $at${failed:+: $failed}"
        return 0
    fi
    missing=""
    while IFS= read -r c; do
        [[ -z "$c" ]] && continue
        case "$(jq -r --arg c "$c" '.matrix[$c] // "missing"' <<< "$conclusive")" in
            pass|not_applicable) ;;
            *) missing="${missing:+$missing, }$c" ;;
        esac
    done <<< "$(lcm_required "$h" "$LR_LLM")"
    if [[ -n "$missing" ]]; then
        LCM_STATE="unverified"
        LCM_REASON="the test of $at passed, but not every capability this binding needs: $missing"
        return 0
    fi
    LCM_STATE="supported"
    LCM_REASON="passed its test of $at"
    return 0
}
