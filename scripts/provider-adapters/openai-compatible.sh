#!/usr/bin/env bash
set -euo pipefail

# openai-compatible.sh — Provider adapter for OpenAI-compatible HTTP APIs
#
# Sends the review request as a chat completion to any OpenAI-compatible
# endpoint (OpenAI, Azure OpenAI, vLLM, llama.cpp, GDX Spark, LM Studio, etc.).
#
# Usage: openai-compatible.sh --base-url URL --model MODEL --input FILE \
#            [--api-key-env VAR] [--max-tokens N] [--temperature T]
#
# Output: Assistant response text on stdout.
# Exit:   0 = success, 1 = error

# ── Parse arguments ──────────────────────────────────────────

BASE_URL=""
API_KEY_ENV=""
MODEL=""
MAX_TOKENS="4096"
TEMPERATURE="0.1"
INPUT_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --base-url)     BASE_URL="${2:?--base-url requires a URL}"; shift 2 ;;
        --api-key-env)  API_KEY_ENV="${2:?--api-key-env requires a var name}"; shift 2 ;;
        --model)        MODEL="${2:?--model requires a model name}"; shift 2 ;;
        --max-tokens)   MAX_TOKENS="${2:?--max-tokens requires a number}"; shift 2 ;;
        --temperature)  TEMPERATURE="${2:?--temperature requires a value}"; shift 2 ;;
        --input)        INPUT_FILE="${2:?--input requires a file path}"; shift 2 ;;
        --no-thinking)  NO_THINKING=true; shift ;;
        -h|--help)
            echo "Usage: openai-compatible.sh --base-url URL --model MODEL --input FILE"
            echo "       [--api-key-env VAR] [--max-tokens N] [--temperature T] [--no-thinking]"
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

# #193 out-of-band cost channel hook: this adapter writes
# CCT_REVIEW_COST_FILE only when it can derive a REAL USD figure. The
# API returns token usage but no price, and inventing a price table
# here would be false measurement — so today it writes nothing and the
# invocation is honestly unmetered (the driver debits its conservative
# estimate). Priced deployments can extend this block with their own
# usage->USD mapping:
#   jq -n --argjson usd "$COMPUTED_USD" '{total_cost_usd: $usd}' > "$CCT_REVIEW_COST_FILE"

echo "$ASSISTANT_CONTENT"
