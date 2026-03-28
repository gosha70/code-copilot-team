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
        -h|--help)
            echo "Usage: openai-compatible.sh --base-url URL --model MODEL --input FILE"
            echo "       [--api-key-env VAR] [--max-tokens N] [--temperature T]"
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

REQUEST_BODY=$(jq -n \
    --arg model "$MODEL" \
    --arg content "$CONTENT" \
    --argjson max_tokens "$MAX_TOKENS" \
    --argjson temperature "$TEMPERATURE" \
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
    }')

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

RESPONSE=$(curl "${CURL_ARGS[@]}" 2>&1) || {
    EXIT_CODE=$?
    echo "Error: curl request to $ENDPOINT failed (exit $EXIT_CODE)" >&2
    if [[ -n "${RESPONSE:-}" ]]; then
        echo "Response: $RESPONSE" >&2
    fi
    exit 1
}

# ── Extract response ─────────────────────────────────────────

# Parse the assistant message content from the response
ASSISTANT_CONTENT=$(echo "$RESPONSE" | jq -r '.choices[0].message.content // empty' 2>/dev/null)

if [[ -z "$ASSISTANT_CONTENT" ]]; then
    # Check for error response
    ERROR_MSG=$(echo "$RESPONSE" | jq -r '.error.message // empty' 2>/dev/null)
    if [[ -n "$ERROR_MSG" ]]; then
        echo "Error: API returned error: $ERROR_MSG" >&2
    else
        echo "Error: Could not extract response content from API response" >&2
        echo "Raw response: $RESPONSE" >&2
    fi
    exit 1
fi

echo "$ASSISTANT_CONTENT"
