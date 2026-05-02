#!/usr/bin/env bash
set -euo pipefail

# notify.sh — Desktop notification hook (Notification event)
#
# Sends a workspace-aware notification when Claude Code fires a notification
# event (permission prompt, idle, etc.). Uses cmux notifications when Claude
# is running inside cmux; otherwise falls back to native desktop notifications.
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

# --- Prefer cmux notifications when running inside cmux ---
if [[ -n "${CMUX_WORKSPACE_ID:-}" ]] && command -v cmux &>/dev/null; then
  cmux notify --title "$TITLE" --body "$MESSAGE" >/dev/null 2>&1 || true
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
