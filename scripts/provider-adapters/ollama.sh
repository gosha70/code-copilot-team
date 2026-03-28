#!/usr/bin/env bash
set -euo pipefail

# ollama.sh — Provider adapter for Ollama instances (local or remote)
#
# Uses `ollama run` CLI for local instances and HTTP API for remote hosts.
#
# Usage: ollama.sh --model MODEL --input FILE [--host HOST:PORT]
#
# Output: Model response text on stdout.
# Exit:   0 = success, 1 = error

# ── Parse arguments ──────────────────────────────────────────

MODEL=""
HOST="localhost:11434"
INPUT_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)  MODEL="${2:?--model requires a model name}"; shift 2 ;;
        --host)   HOST="${2:?--host requires a host:port}"; shift 2 ;;
        --input)  INPUT_FILE="${2:?--input requires a file path}"; shift 2 ;;
        -h|--help)
            echo "Usage: ollama.sh --model MODEL --input FILE [--host HOST:PORT]"
            exit 0
            ;;
        *)
            echo "Error: Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# ── Validate required arguments ──────────────────────────────

if [[ -z "$MODEL" ]]; then
    echo "Error: --model is required" >&2
    exit 1
fi

if [[ -z "$INPUT_FILE" || ! -f "$INPUT_FILE" ]]; then
    echo "Error: --input requires a valid file path" >&2
    exit 1
fi

# ── Determine local vs remote ────────────────────────────────

is_local() {
    local host_part="${HOST%%:*}"
    [[ "$host_part" == "localhost" || "$host_part" == "127.0.0.1" || "$host_part" == "::1" ]]
}

# ── Execute ──────────────────────────────────────────────────

if is_local && command -v ollama &>/dev/null; then
    # Local: use ollama CLI directly
    # Set OLLAMA_HOST if non-default port
    if [[ "$HOST" != "localhost:11434" && "$HOST" != "127.0.0.1:11434" ]]; then
        export OLLAMA_HOST="$HOST"
    fi

    RESPONSE=$(ollama run "$MODEL" < "$INPUT_FILE" 2>&1) || {
        EXIT_CODE=$?
        echo "Error: ollama run failed (exit $EXIT_CODE)" >&2
        if [[ -n "${RESPONSE:-}" ]]; then
            echo "Output: $RESPONSE" >&2
        fi
        exit 1
    }

    echo "$RESPONSE"
else
    # Remote (or local without CLI): use HTTP API
    if ! command -v jq &>/dev/null; then
        echo "Error: jq is required for remote Ollama API calls" >&2
        exit 1
    fi

    CONTENT=$(cat "$INPUT_FILE")

    REQUEST_BODY=$(jq -n \
        --arg model "$MODEL" \
        --arg prompt "$CONTENT" \
        '{
            model: $model,
            prompt: $prompt,
            stream: false
        }')

    API_URL="http://${HOST}/api/generate"

    RESPONSE=$(curl -sf -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -d "$REQUEST_BODY" 2>&1) || {
        EXIT_CODE=$?
        echo "Error: curl request to $API_URL failed (exit $EXIT_CODE)" >&2
        if [[ -n "${RESPONSE:-}" ]]; then
            echo "Response: $RESPONSE" >&2
        fi
        exit 1
    }

    # Extract response text from Ollama API response
    RESPONSE_TEXT=$(echo "$RESPONSE" | jq -r '.response // empty' 2>/dev/null)

    if [[ -z "$RESPONSE_TEXT" ]]; then
        ERROR_MSG=$(echo "$RESPONSE" | jq -r '.error // empty' 2>/dev/null)
        if [[ -n "$ERROR_MSG" ]]; then
            echo "Error: Ollama API returned error: $ERROR_MSG" >&2
        else
            echo "Error: Could not extract response from Ollama API" >&2
            echo "Raw response: $RESPONSE" >&2
        fi
        exit 1
    fi

    echo "$RESPONSE_TEXT"
fi
