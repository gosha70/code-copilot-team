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
rr_doc_invariant() {
    jq -e --arg classes "$RR_CLASSES" '
        if .outcome == "success" then .failure_class == null
        elif .outcome == "failure" then
            (.failure_class | type == "string")
            and ([.failure_class] | inside($classes | split(" ")))
        else false end' >/dev/null 2>&1 <<< "$1"
}

# rr_result <exit_code> <output_file> <backend> <provider> <profile>
#           <requested_model> <effective_model|-> <quota_pool>
#           [upstream_origin|-] [artifacts_json]
# Composes the full routing-result document (schema above); the
# classification comes from rr_classify over the SAME capture.
rr_result() {
    local rc="$1" file="$2" backend="$3" provider="$4" profile="$5"
    local reqm="$6" effm="$7" pool="$8" origin="${9:--}" artifacts="${10:-{\}}"
    local cls
    cls=$(rr_classify "$rc" "$file") || return 1
    jq -n --argjson cls "$cls" --arg backend "$backend" --arg provider "$provider" \
          --arg profile "$profile" --arg reqm "$reqm" --arg effm "$effm" \
          --arg pool "$pool" --arg origin "$origin" --argjson rc "$rc" \
          --argjson artifacts "$artifacts" '
        $cls + {schema_version:1, backend:$backend, provider:$provider, profile:$profile,
                requested_model:$reqm,
                effective_model:(if $effm == "-" then null else $effm end),
                quota_pool:$pool, exit_code:$rc,
                upstream_origin:(if $origin == "-" then null else $origin end),
                artifacts:$artifacts}'
}
