#!/usr/bin/env bash
# cct-canary.sh — the canary primitives two probes share (#400 FR-15,
# D6): the routing probe (routing-probe.sh) and the LLM catalog's probe
# (llm-probe.sh). Each probe keeps its own accounting, verdicts and
# state; only these are common.
#
#   cn_nonce <seed>              20 hex characters of the seed's SHA-256
#   cn_prompt <tools:0|1> <reply> [<command>]
#                                the canary prompt: run <command> with the
#                                Bash tool (when tools is 1), then reply
#                                with <reply>
#   cn_tool_ran <file> <marker>  0 when the marker file holds the marker
#   cn_json_records <file>       the backend's JSON records, one per line
#   cn_result_text <file>        only the reply the backend wrote
#   cn_scrub <file> <secret> <name>
#                                replaces the secret's value in the file
#                                with [REDACTED:<name>]
#   rr_classify                  the failure classifier, routing-result.sh
#
# bash 3.2; jq only.

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/routing-result.sh"

CN_MARKER="CCT_PROBE_OK"
CN_TOOL_MARKER="CCT_TOOL_OK"

cn_nonce() {
    printf '%s' "$1" \
        | { command -v shasum >/dev/null 2>&1 && shasum -a 256 || sha256sum; } \
        | cut -c1-20
}

cn_prompt() {
    if [[ "$1" == "1" ]]; then
        printf 'Health canary. Do BOTH, nothing else:\n1. Run this exact shell command with your Bash tool: %s\n2. Then reply with %s\n' "$3" "$2"
    else
        printf 'Health canary. Reply with %s\n' "$2"
    fi
}

cn_tool_ran() {
    [[ -s "$1" ]] && grep -q "$2" "$1" 2>/dev/null
}

# Read the backend's JSON/JSONL records without letting one diagnostic
# line invalidate every structured record around it. First accept a
# wholly valid JSON stream (including pretty-printed JSON); otherwise
# fall back to independently parsing complete JSON lines and ignore
# non-JSON notices. Consumers still apply their own closed shapes.
cn_json_records() {
    local records
    if records=$(jq -c . "$1" 2>/dev/null); then
        printf '%s\n' "$records"
    else
        jq -Rc 'fromjson?' "$1" 2>/dev/null || true
    fi
}

# Parse only a backend-authored response field. The prompt itself also
# appears in several CLI transcript shapes; grepping the merged stream
# lets a backend that merely echoes its input manufacture health. The
# accepted shapes mirror the repo's headless-session contract: a result
# object's `result`, or the last assistant text message. A raw line or a
# user/prompt event is never positive evidence.
cn_result_text() {
    cn_json_records "$1" | jq -r -s '
      map(if type == "array" then .[] else . end) as $docs
      | ([ $docs[] | select(type == "object" and .type? == "result"
                            and ((.result? | type) == "string"))
           | .result ] | last)
        // ([ $docs[] | select(type == "object" and .type? == "assistant")
              | if ((.message?.content? | type) == "array") then
                  [ .message.content[]
                    | select(type == "object" and .type? == "text"
                             and ((.text? | type) == "string"))
                    | .text ] | join("")
                elif ((.message? | type) == "string") then .message
                elif ((.content? | type) == "string") then .content
                else empty end ] | last)
        // (if ($docs | length) == 1
               and (($docs[0] | type) == "object")
               and (($docs[0].result? | type) == "string")
            then $docs[0].result else empty end)
        // empty
      | gsub("^\\s+|\\s+$"; "")' 2>/dev/null || true
}

# Scrub BEFORE anything persists or is classified. An empty secret
# changes nothing.
cn_scrub() {
    local content
    [[ -n "$2" ]] || return 0
    content="$(cat "$1" 2>/dev/null)"
    printf '%s\n' "${content//"$2"/[REDACTED:$3]}" > "$1"
}
