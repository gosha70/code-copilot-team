#!/usr/bin/env bash
set -euo pipefail

# openai-compatible.sh — Provider adapter for OpenAI-compatible HTTP APIs
#
# Sends the review request as a chat completion to any OpenAI-compatible
# endpoint (OpenAI, Azure OpenAI, vLLM, llama.cpp, GDX Spark, LM Studio, etc.).
#
# Usage: openai-compatible.sh --base-url URL --model MODEL --input FILE \
#            [--api-key-env VAR] [--max-tokens N] [--temperature T] [--no-thinking] \
#            [--price-input USD_PER_MTOK --price-output USD_PER_MTOK]
#
# Output: Assistant response text on stdout.
# Exit:   0 = success, 1 = error
#
# With both --price-* set (providers.toml price_usd_per_mtok_input /
# price_usd_per_mtok_output) and CCT_REVIEW_COST_FILE in the
# environment, the response's `usage` token counts are priced at those
# rates and written to the cost file as a CONSERVATIVE CALCULATED cost
# — configured peak, cache-miss rates times measured tokens, never the
# exact bill when caching or off-peak discounts apply. It is written
# before the answer is judged, so a reply that spent its budget on
# hidden reasoning still records what it consumed. A response with no
# usable `usage` writes nothing (the driver's estimate then applies).

# ── Parse arguments ──────────────────────────────────────────

BASE_URL=""
API_KEY_ENV=""
MODEL=""
MAX_TOKENS="4096"
TEMPERATURE="0.1"
INPUT_FILE=""
PRICE_INPUT=""
PRICE_OUTPUT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --base-url)     BASE_URL="${2:?--base-url requires a URL}"; shift 2 ;;
        --api-key-env)  API_KEY_ENV="${2:?--api-key-env requires a var name}"; shift 2 ;;
        --model)        MODEL="${2:?--model requires a model name}"; shift 2 ;;
        --max-tokens)   MAX_TOKENS="${2:?--max-tokens requires a number}"; shift 2 ;;
        --temperature)  TEMPERATURE="${2:?--temperature requires a value}"; shift 2 ;;
        --input)        INPUT_FILE="${2:?--input requires a file path}"; shift 2 ;;
        --no-thinking)  NO_THINKING=true; shift ;;
        --price-input)  PRICE_INPUT="${2:?--price-input requires USD per million tokens}"; shift 2 ;;
        --price-output) PRICE_OUTPUT="${2:?--price-output requires USD per million tokens}"; shift 2 ;;
        -h|--help)
            echo "Usage: openai-compatible.sh --base-url URL --model MODEL --input FILE"
            echo "       [--api-key-env VAR] [--max-tokens N] [--temperature T] [--no-thinking]"
            echo "       [--price-input USD_PER_MTOK --price-output USD_PER_MTOK]"
            exit 0
            ;;
        *)
            echo "Error: Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# ── Validate required arguments ──────────────────────────────

if [[ -z "$BASE_URL" ]]; then
    echo "Error: --base-url is required" >&2
    exit 1
fi

if [[ -z "$MODEL" ]]; then
    echo "Error: --model is required" >&2
    exit 1
fi

if [[ -z "$INPUT_FILE" || ! -f "$INPUT_FILE" ]]; then
    echo "Error: --input requires a valid file path" >&2
    exit 1
fi

# Pricing is all-or-nothing: one rate without the other cannot price a
# request, and pricing half of it would understate.
if [[ -n "$PRICE_INPUT" || -n "$PRICE_OUTPUT" ]]; then
    if [[ -z "$PRICE_INPUT" || -z "$PRICE_OUTPUT" ]]; then
        echo "Error: --price-input and --price-output must be given together" >&2
        exit 1
    fi
    for _rate in "$PRICE_INPUT" "$PRICE_OUTPUT"; do
        if ! awk -v v="$_rate" 'BEGIN { exit !(v ~ /^[0-9]+(\.[0-9]+)?$/ && v + 0 >= 0) }'; then
            echo "Error: a price must be a non-negative number of USD per million tokens, got '$_rate'" >&2
            exit 1
        fi
    done
fi

# ── Resolve API key ──────────────────────────────────────────

AUTH_HEADER=""
if [[ -n "$API_KEY_ENV" ]]; then
    API_KEY="${!API_KEY_ENV:-}"
    if [[ -z "$API_KEY" ]]; then
        echo "Error: Environment variable '$API_KEY_ENV' is not set or empty" >&2
        exit 1
    fi
    AUTH_HEADER="Authorization: Bearer $API_KEY"
fi

# ── Build request body ───────────────────────────────────────

# Read the review request content and escape for JSON
CONTENT=$(cat "$INPUT_FILE")

# Use jq to build a properly escaped JSON payload
if ! command -v jq &>/dev/null; then
    echo "Error: jq is required but not installed" >&2
    exit 1
fi

# --no-thinking (providers.toml `disable_thinking = true`): reasoning
# models served by vLLM (Qwen3 family) spend the answer budget on hidden
# reasoning and return content: null — the third real unattended run
# (#190, 2026-09-09) lost its review round to exactly that. vLLM turns
# thinking off per request with chat_template_kwargs; a server that
# rejects the field (400 naming it) is asked again without it.
NO_THINKING="${NO_THINKING:-false}"
build_request_body() {
    local with_thinking_off="$1"
    jq -n \
        --arg model "$MODEL" \
        --arg content "$CONTENT" \
        --argjson max_tokens "$MAX_TOKENS" \
        --argjson temperature "$TEMPERATURE" \
        --argjson no_thinking "$with_thinking_off" \
        '{
            model: $model,
            messages: [
                {
                    role: "user",
                    content: $content
                }
            ],
            max_tokens: $max_tokens,
            temperature: $temperature
        } + (if $no_thinking then {chat_template_kwargs: {enable_thinking: false}} else {} end)'
}
REQUEST_BODY=$(build_request_body "$NO_THINKING")

# ── Send request ─────────────────────────────────────────────

ENDPOINT="${BASE_URL%/}/chat/completions"

CURL_ARGS=(
    -sf
    -X POST
    "$ENDPOINT"
    -H "Content-Type: application/json"
    -d "$REQUEST_BODY"
)

if [[ -n "$AUTH_HEADER" ]]; then
    CURL_ARGS+=(-H "$AUTH_HEADER")
fi

# -sf hides the body of a 4xx; a 400 that names chat_template_kwargs is
# the one case worth a second request, so the body is read without -f
# and the status is judged here.
send_request() {
    local body="$1" out
    out=$(curl -s -w '\n%{http_code}' -X POST "$ENDPOINT" -H "Content-Type: application/json" \
        ${AUTH_HEADER:+-H "$AUTH_HEADER"} -d "$body" 2>&1) || return 1
    HTTP_STATUS=$(printf '%s' "$out" | tail -n 1)
    RESPONSE=$(printf '%s' "$out" | sed '$d')
    case "$HTTP_STATUS" in
        2*) return 0 ;;
        *)  return 2 ;;
    esac
}
RESPONSE=""; HTTP_STATUS=""
rc=0; send_request "$REQUEST_BODY" || rc=$?
if [[ "$rc" -ne 0 ]]; then
    if [[ "$rc" -eq 2 && "$NO_THINKING" == "true" && "$HTTP_STATUS" == "400" && "$RESPONSE" == *chat_template_kwargs* ]]; then
        # The server does not know the field: ask without it.
        REQUEST_BODY=$(build_request_body false)
        rc=0; send_request "$REQUEST_BODY" || rc=$?
    fi
    if [[ "$rc" -ne 0 ]]; then
        echo "Error: request to $ENDPOINT failed (HTTP ${HTTP_STATUS:-none})" >&2
        if [[ -n "${RESPONSE:-}" ]]; then
            echo "Response: $RESPONSE" >&2
        fi
        exit 1
    fi
fi

# ── Price the usage (before the answer is judged) ────────────

# #193 out-of-band cost channel: the adapter writes CCT_REVIEW_COST_FILE
# only when it can derive a REAL figure. With configured rates and the
# response's usage counts it can: tokens times peak cache-miss rates —
# a conservative calculated cost, never the exact bill. Written HERE,
# before the content check, so a reply that spent its whole budget on
# hidden reasoning still records the tokens it consumed. Unusable usage
# (absent, non-numeric) writes nothing: the driver's estimate applies.
if [[ -n "$PRICE_INPUT" && -n "${CCT_REVIEW_COST_FILE:-}" ]]; then
    PRICED=$(printf '%s' "$RESPONSE" | jq -c --arg pin "$PRICE_INPUT" --arg pout "$PRICE_OUTPUT" '
        .usage as $u
        | if ($u | type) == "object"
             and (($u.prompt_tokens | type) == "number") and ($u.prompt_tokens >= 0)
             and (($u.completion_tokens | type) == "number") and ($u.completion_tokens >= 0)
          then {
            total_cost_usd: (($u.prompt_tokens * ($pin | tonumber) + $u.completion_tokens * ($pout | tonumber)) / 1000000),
            prompt_tokens: $u.prompt_tokens,
            completion_tokens: $u.completion_tokens,
            price_usd_per_mtok_input: ($pin | tonumber),
            price_usd_per_mtok_output: ($pout | tonumber),
            basis: "conservative calculated cost: measured tokens at configured peak cache-miss rates"
          }
          else empty end' 2>/dev/null || true)
    if [[ -n "$PRICED" ]]; then
        printf '%s\n' "$PRICED" > "$CCT_REVIEW_COST_FILE"
    fi
fi

# ── Extract response ─────────────────────────────────────────

# Parse the assistant message content from the response
ASSISTANT_CONTENT=$(echo "$RESPONSE" | jq -r '.choices[0].message.content // empty' 2>/dev/null)

if [[ -z "$ASSISTANT_CONTENT" ]]; then
    # Check for error response
    ERROR_MSG=$(echo "$RESPONSE" | jq -r '.error.message // empty' 2>/dev/null)
    REASONING_CHARS=$(echo "$RESPONSE" | jq -r '(.choices[0].message.reasoning // .choices[0].message.reasoning_content // "") | length' 2>/dev/null || echo 0)
    FINISH=$(echo "$RESPONSE" | jq -r '.choices[0].finish_reason // empty' 2>/dev/null)
    if [[ -n "$ERROR_MSG" ]]; then
        echo "Error: API returned error: $ERROR_MSG" >&2
    elif [[ "${REASONING_CHARS:-0}" -gt 0 ]]; then
        # The model answered — in its hidden reasoning, with nothing
        # left for the answer. Name the cause and the fix.
        echo "Error: the model returned no content: it spent its ${MAX_TOKENS}-token budget on hidden reasoning (${REASONING_CHARS} chars, finish_reason ${FINISH:-unknown}). Set disable_thinking = true for this provider in providers.toml (sent as chat_template_kwargs.enable_thinking=false), or raise max_tokens." >&2
    else
        echo "Error: Could not extract response content from API response" >&2
        echo "Raw response: $RESPONSE" >&2
    fi
    exit 1
fi

# Without configured rates the API's usage has no price, and inventing
# one here would be false measurement — nothing is written and the
# invocation is honestly unmetered (the driver debits its estimate).

echo "$ASSISTANT_CONTENT"
