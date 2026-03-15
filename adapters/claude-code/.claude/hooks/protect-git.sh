#!/usr/bin/env bash
set -euo pipefail

# protect-git.sh — PreToolUse hook (Bash matcher)
#
# Blocks git commit and git push commands unless the user has explicitly
# instructed them. Exit 0 = allow, Exit 2 = block.
#
# This hook prevents Claude from committing or pushing without user
# approval, even when auto-accept mode is enabled.
#
# Override: set HOOK_GIT_ALLOW=true to disable this guard.

# --- Override check ---
if [[ "${HOOK_GIT_ALLOW:-false}" == "true" ]]; then
  exit 0
fi

# --- jq guard ---
if ! command -v jq &>/dev/null; then
  exit 0
fi

# --- Read event JSON from stdin ---
INPUT=$(cat)

COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null) || exit 0
if [[ -z "$COMMAND" ]]; then
  exit 0
fi

# --- Normalize: collapse whitespace, strip leading whitespace ---
COMMAND_NORMALIZED=$(echo "$COMMAND" | tr '\n' ' ' | sed 's/  */ /g; s/^ //')

# --- Check for git commit ---
if echo "$COMMAND_NORMALIZED" | grep -qE '(^|&&\s*|;\s*|\|\|\s*)git\s+commit\b'; then
  echo "Blocked: git commit requires explicit user instruction. Show the diff summary first, propose a commit message, and wait for the user to say 'commit', 'yes', or 'go ahead'. Do not commit in response to questions like 'what is the commit message'." >&2
  exit 2
fi

# --- Check for git push ---
if echo "$COMMAND_NORMALIZED" | grep -qE '(^|&&\s*|;\s*|\|\|\s*)git\s+push\b'; then
  echo "Blocked: git push requires explicit user instruction. Never push automatically after a commit. Wait for the user to explicitly request a push." >&2
  exit 2
fi

# --- Not a git commit/push: allow ---
exit 0
