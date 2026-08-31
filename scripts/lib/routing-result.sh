#!/usr/bin/env bash
# routing-result.sh — normalized backend-result classifier (#248 T2,
# increment A of #109; plan decision 5 + the T2 precedence pin).
#
# Classifies CAUSE, never provider wording and never routing action:
# increment B owns the mapping from failure_class to routing behavior.
#
# PRECEDENCE IS EXPLICIT, not an accident of regex order:
#   1. structured provider error envelope (method: structured, high)
#   2. specific semantic signals, most-specific first:
#        quota_exhausted -> rate_limited -> auth -> denied
#        -> invalid_request
#      (quota before rate: a message carrying BOTH an exhaustion signal
#       and throttle wording is pool exhaustion — hours-scale — and
#       must not be read as a short throttle)
#   3. generic availability: unavailable -> transport -> execution
#   4. unknown — the FAIL-CLOSED residual. Never a catch-all class
#      with semantics; no retry/failover behavior may attach to it.
#
# An HTTP status code ALONE never determines semantic cause: every
# predicate requires affirmative text (a bare "HTTP 403 Forbidden" is
# unknown — it may be quota, credentials, or policy). `denied` requires
# an AFFIRMATIVE policy-denial signal.

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/routing-usage.sh"

RR_CLASSES="quota_exhausted rate_limited unavailable transport auth invalid_request denied execution unknown"

# Each predicate is a named grep -iE pattern (also recorded as
# evidence.pattern). Kept one-per-class so a weakened pattern is
# visible in evidence, and so tests can mutate exactly one.
RR_PAT_QUOTA="(hit|reached) your (session|weekly|usage|5-hour) limit|(session|weekly|usage) limit (reached|hit|exhausted)|limit will reset|subscription (usage )?limit"
RR_PAT_RATE="rate[- _]?limit|too many requests|retry-after"
RR_PAT_AUTH="authentication[_ ]error|invalid (x-)?api[- ]?key|unauthorized|invalid bearer|credit balance|billing (issue|problem|configuration)|api key (invalid|expired|revoked)"
RR_PAT_DENIED="(blocked|denied|rejected) by .*polic|content polic(y|ies) (violation|denial|block)|policy deni|compliance deni|protected[- ]path deni|data[- ]egress deni"
RR_PAT_INVALID="context (length|window)|maximum context|prompt is too long|too many tokens|invalid_request_error|validation error|should be a valid|unsupported (tool|model|parameter|content block)"
RR_PAT_UNAVAILABLE="overloaded|service unavailable|internal server error|bad gateway|upstream connect error|server had an error"
RR_PAT_TRANSPORT="connection refused|could not resolve host|name or service not known|connection (reset|closed)|timed out|econnrefused|etimedout|network is unreachable|curl: \([0-9]+\)"
RR_PAT_EXECUTION="tests? failed|assertion(error| failed)|FAIL:|build failed|lint (failed|errors)|type ?check failed|npm err!"

# The EXPLICIT numeric server maximum (#109 increment F, FR-F4/plan
# D4). Kept separate from RR_PAT_INVALID on purpose: that pattern
# decides the CLASS, this one extracts a VALUE, and the value is read
# ONLY from output already classified invalid_request. A number inside
# an auth or transport failure is not a context limit. Vague overflow
# wording ("prompt is too long", no number) matches nothing here and
# records null — which leaves today's attempt-local incompatibility
# behavior untouched.
# A CONNECTOR is required between the phrase and the number. The
# earlier loose form ("context length" + up to 24 non-digits + digits)
# turned "maximum context length exceeded (error 42)" into a durable
# 42-token cap and "code 503" into 503 — a misparse that permanently
# strands a profile. It also demanded two digits, wrongly rejecting a
# legitimate small limit. Now: the phrase, optional whitespace, one of
# is/of/=/:/, then the number.
RR_PAT_CTX_NUM="context (length|window)[[:space:]]*(is|of|=|:)[[:space:]]*[0-9]+"

# rr_context_limit_observed <output_file> <class> — the numeric ceiling
# on stdout, or empty. Empty is the normal answer.
rr_context_limit_observed() {
    [[ "$2" == "invalid_request" ]] || return 0
    [[ -r "$1" ]] || return 0
    # take the digits AFTER the connector, never the first number on
    # the line — the phrase itself may contain one (e.g. "gpt-4").
    grep -ioE "$RR_PAT_CTX_NUM" "$1" 2>/dev/null | head -1 \
        | grep -oE '[0-9]+$' | head -1 || true
}

# Structured Anthropic-style envelope error.type -> class.
_rr_structured_class() {  # <error.type> -> class or ""
    case "$1" in
        rate_limit_error)                       echo "rate_limited" ;;
        authentication_error|billing_error)     echo "auth" ;;
        permission_error)                       echo "" ;;  # ambiguous: quota, credentials, or policy — fall through to text
        overloaded_error|api_error)             echo "unavailable" ;;
        invalid_request_error)                  echo "invalid_request" ;;
        *)                                      echo "" ;;
    esac
}

# rr_classify <exit_code> <output_file>
# Emits {"outcome","failure_class","retry_after_sec","reset_at",
#        "evidence":{method,confidence,pattern,source_artifact}}
rr_classify() {
    local rc="$1" file="$2"
    local class="" method="regex" confidence="medium" pattern="" retry="null" reset="null"

    if [[ "$rc" == "0" ]]; then
        jq -n '{outcome:"success", failure_class:null, retry_after_sec:null, reset_at:null,
                evidence:{method:"structured", confidence:"high", pattern:null, source_artifact:null}}'
        return 0
    fi

    local text=""
    [[ -r "$file" ]] && text="$(cat "$file")"

    # retry/reset metadata ride beside the class, whatever it is
    local m
    if m=$(grep -ioE 'retry-after[: ]+[0-9]+' "$file" 2>/dev/null | head -1 | grep -oE '[0-9]+'); then
        [[ -n "$m" ]] && retry="$m"
    fi
    if m=$(grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(Z|[+-][0-9]{2}:?[0-9]{2})?' "$file" 2>/dev/null | head -1); then
        [[ -n "$m" ]] && reset="\"$m\""
    fi

    # 1. structured envelope
    local envline etype
    envline=$(grep -o '{"type":"error".*}' "$file" 2>/dev/null | head -1 || true)
    if [[ -n "$envline" ]] && etype=$(printf '%s' "$envline" | jq -r '.error.type // empty' 2>/dev/null) && [[ -n "$etype" ]]; then
        class=$(_rr_structured_class "$etype")
        if [[ -n "$class" ]]; then
            method="structured"; confidence="high"; pattern="error.type=$etype"
        fi
    fi

    # 2-3. the explicit semantic ladder (specific -> generic)
    if [[ -z "$class" ]]; then
        local c p
        for c in quota_exhausted rate_limited auth denied invalid_request unavailable transport execution; do
            case "$c" in
                quota_exhausted) p="$RR_PAT_QUOTA" ;;
                rate_limited)    p="$RR_PAT_RATE" ;;
                auth)            p="$RR_PAT_AUTH" ;;
                denied)          p="$RR_PAT_DENIED" ;;
                invalid_request) p="$RR_PAT_INVALID" ;;
                unavailable)     p="$RR_PAT_UNAVAILABLE" ;;
                transport)       p="$RR_PAT_TRANSPORT" ;;
                execution)       p="$RR_PAT_EXECUTION" ;;
            esac
            if printf '%s' "$text" | grep -qiE "$p"; then
                class="$c"; pattern="$p"; break
            fi
        done
    fi

    # 4. the fail-closed residual
    if [[ -z "$class" ]]; then
        class="unknown"; method="regex"; confidence="low"; pattern=""
    fi

    jq -n --arg class "$class" --arg method "$method" --arg conf "$confidence" \
          --arg pattern "$pattern" --argjson retry "$retry" --argjson reset "$reset" '
        {outcome:"failure", failure_class:$class,
         retry_after_sec:$retry, reset_at:$reset,
         evidence:{method:$method, confidence:$conf,
                   pattern:(if $pattern == "" then null else $pattern end),
                   source_artifact:null}}'
}

# rr_doc_invariant <json-string> — the frozen normalization boundary,
# BIDIRECTIONAL: outcome success <=> failure_class null, and a failure
# must carry one of the nine causes (`unknown` exists precisely so no
# failed invocation ever needs null). B consumes failure_class to pick
# an action; a failed document with no cause is internally
# contradictory and is refused HERE, not guessed at downstream.
#
# The context-limit group (#109 increment F) is enforced HERE rather
# than in the JSON schema, deliberately. Making the four fields
# `required` in schema version 1 would invalidate every version-1
# record written before F; introducing version 2 would fork the
# contract for a purely additive group. So the schema keeps them
# OPTIONAL for legacy compatibility, and this runtime boundary — which
# only ever sees documents F itself just produced — requires them to
# be present and internally consistent. Old records stay readable; new
# records cannot omit the group or contradict themselves.
#
# VERSION BOUNDARY: schema_version must be exactly 1. Today's reader
# must never interpret a FUTURE, incompatible record as though it were
# today's shape — a durable record that outlives this code is exactly
# where that mistake becomes silent data corruption. Unknown version =
# explicit refusal, never best-effort.
rr_doc_invariant() {
    jq -e --arg classes "$RR_CLASSES" '
        (.schema_version == 1)
        and (if .outcome == "success" then .failure_class == null
         elif .outcome == "failure" then
             (.failure_class | type == "string")
             and ([.failure_class] | inside($classes | split(" ")))
         else false end)
        and (has("context_limit_declared") and has("context_limit_observed")
             and has("context_limit_effective") and has("context_limit_evidence"))
        and has("usage")
        # evidence exists exactly when an observation does
        and ((.context_limit_observed == null) == (.context_limit_evidence == null))
        # an observation NEVER substitutes for a declaration (FR-F6)
        and (if .context_limit_declared == null
             then .context_limit_effective == null
             else .context_limit_effective ==
                  (if .context_limit_observed != null
                      and .context_limit_observed < .context_limit_declared
                   then .context_limit_observed
                   else .context_limit_declared end)
             end)' >/dev/null 2>&1 <<< "$1" || return 1
    # the usage block's own shape (#273 increment G) — delegated so the
    # two libraries keep one definition of the contract each
    ru_doc_invariant "$(jq -c '.usage' <<< "$1")"
}

# rr_result <exit_code> <output_file> <backend> <provider> <profile>
#           <requested_model> <effective_model|-> <quota_pool>
#           [upstream_origin|-] [artifacts_json] [declared_context_limit|-]
# Composes the full routing-result document (schema above); the
# classification comes from rr_classify over the SAME capture.
#
# The context-limit group (#109 increment F, FR-F8) records all four
# facts rather than a single collapsed number: what the operator
# DECLARED, what the provider was OBSERVED to enforce, which one is
# EFFECTIVE, and the evidence source. `effective` is null whenever
# `declared` is null even if something was observed — an overflow
# ceiling is an upper bound seen while failing, never a proof of
# capacity (FR-F6), so it has nothing to narrow and cannot stand in
# for a declaration.
# The PRIOR argument is the identity-bound observation that governed
# THIS attempt's selection. Without it the record lies about what was
# enforced: an attempt constrained to 32768 by an earlier observation
# that then SUCCEEDS carries no overflow of its own, so a
# declaration-only computation would report 200000 as effective — the
# telemetry would contradict the routing decision it is supposed to
# explain.
rr_result() {
    local rc="$1" file="$2" backend="$3" provider="$4" profile="$5"
    local reqm="$6" effm="$7" pool="$8" origin="${9:--}" artifacts="${10:-{\}}"
    local declared="${11:--}" prior="${12:--}"
    # The usage SOURCE is separate from the classification source: the
    # supervisor's main path wraps the auto-build driver, whose stdout
    # is a console log rather than a backend result stream, so usage
    # there is joined from the driver's published artifact instead.
    local ufile="${13:--}" ubackend="${14:--}"
    [[ "$ufile" == "-" ]] && ufile="$file"
    [[ "$ubackend" == "-" ]] && ubackend="$backend"
    local cls class this_obs
    cls=$(rr_classify "$rc" "$file") || return 1
    class=$(jq -r '.failure_class // ""' <<< "$cls")
    this_obs=$(rr_context_limit_observed "$file" "$class")
    # usage/cost evidence (#273, increment G). Composed from THIS
    # attempt's own capture, and never from the driver's cost cap.
    # Priced against the EFFECTIVE (served) model ONLY. A requested
    # model never proves what served the request (#109 C13), so it must
    # never price one — an unverified identity yields `unavailable`.
    local usage urc=0
    usage=$(ru_usage "$ufile" "$ubackend" "${effm:--}") || urc=$?
    if [[ "$urc" -ne 0 ]]; then
        echo "routing-result: refusing to compose a result whose usage evidence could not be resolved (exit $urc)" >&2
        return 1
    fi
    local doc
    doc=$(jq -n -c --argjson cls "$cls" --arg backend "$backend" --arg provider "$provider" \
          --arg profile "$profile" --arg reqm "$reqm" --arg effm "$effm" \
          --arg pool "$pool" --arg origin "$origin" --argjson rc "$rc" \
          --argjson artifacts "$artifacts" \
          --arg decl "$declared" --arg tobs "$this_obs" --arg pobs "$prior" \
          --argjson usage "$usage" '
        ($decl | if . == "-" or . == "" then null else tonumber end) as $d |
        ($tobs | if . == "" then null else tonumber end) as $t |
        ($pobs | if . == "-" or . == "" then null else tonumber end) as $p |
        # the identity total: tightest of this attempt and any prior
        (if $t == null then $p
         elif $p == null then $t
         elif $t < $p then $t else $p end) as $o |
        $cls + {schema_version:1, backend:$backend, provider:$provider, profile:$profile,
                requested_model:$reqm,
                effective_model:(if $effm == "-" then null else $effm end),
                quota_pool:$pool, exit_code:$rc,
                upstream_origin:(if $origin == "-" then null else $origin end),
                context_limit_declared: $d,
                context_limit_observed: $o,
                context_limit_effective:
                  (if $d == null then null
                   elif $o != null and $o < $d then $o
                   else $d end),
                context_limit_evidence:
                  (if $o == null then null
                   elif $t != null and ($p == null or $t <= $p)
                     then "invalid_request numeric maximum (this attempt)"
                   else "prior identity-bound observation" end),
                usage:$usage,
                artifacts:$artifacts}')
    # THE RUNTIME BOUNDARY, actually enforced. Until now rr_doc_invariant
    # was only ever called by tests, so a malformed block could still be
    # persisted despite the strict predicate existing. Construct, then
    # validate, then emit — and REFUSE on failure rather than degrading
    # to `unavailable`, which would hide the defect as missing evidence.
    if ! rr_doc_invariant "$doc"; then
        echo "routing-result: the composed result violates the normalization boundary — refusing to emit it" >&2
        return 1
    fi
    printf '%s\n' "$doc"
}
