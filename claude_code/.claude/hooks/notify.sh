#!/usr/bin/env bash
set -euo pipefail

# notify.sh — Desktop notification hook (Notification event)
#
# Sends a native desktop notification when Claude Code fires a notification
# event (permission prompt, idle, etc.). Cross-platform: macOS + Linux.
#
# Exit: always 0 — notifications are passive, never block.

# --- jq guard ---
if ! command -v jq &>/dev/null; then
  exit 0
fi

# --- Read event JSON from stdin ---
INPUT=$(cat)

TITLE=$(echo "$INPUT" | jq -r '.title // "Claude Code"' 2>/dev/null) || exit 0
MESSAGE=$(echo "$INPUT" | jq -r '.message // ""' 2>/dev/null) || exit 0

if [[ -z "$MESSAGE" ]]; then
  exit 0
fi

# --- Sanitize for shell embedding (escape double quotes) ---
SAFE_TITLE="${TITLE//\"/\'}"
SAFE_MESSAGE="${MESSAGE//\"/\'}"

# --- Send notification ---
case "$(uname -s)" in
  Darwin)
    osascript -e "display notification \"${SAFE_MESSAGE}\" with title \"${SAFE_TITLE}\"" 2>/dev/null || true
    ;;
  Linux)
    if command -v notify-send &>/dev/null; then
      notify-send "$SAFE_TITLE" "$SAFE_MESSAGE" 2>/dev/null || true
    fi
    ;;
esac

exit 0
