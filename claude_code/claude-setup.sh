#!/bin/bash
# claude-setup.sh — Backward-compatible wrapper
#
# Delegates to adapters/claude-code/setup.sh.
# Kept for users who have existing scripts pointing to this path.

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")" && pwd)"
ADAPTER_SETUP="$SCRIPT_DIR/../adapters/claude-code/setup.sh"

if [[ ! -f "$ADAPTER_SETUP" ]]; then
    echo "[ERROR] Adapter setup not found at: $ADAPTER_SETUP"
    echo "        Run from the code-copilot-team repo root."
    exit 1
fi

exec "$ADAPTER_SETUP" "$@"
