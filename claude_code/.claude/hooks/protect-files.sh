#!/usr/bin/env bash
set -euo pipefail

# protect-files.sh — PreToolUse hook (Edit|Write matcher)
#
# Blocks edits to protected files: .env, *.lock, .git/*, credentials, secrets.
# Exit 0 = allow, Exit 2 = block (stderr shown to Claude as reason).
#
# Override: set HOOK_PROTECT_ALLOW=true to disable protection.

# --- Override check ---
if [[ "${HOOK_PROTECT_ALLOW:-false}" == "true" ]]; then
  exit 0
fi

# --- jq guard ---
if ! command -v jq &>/dev/null; then
  echo "jq not found; hook skipped. Install jq for hook support." >&2
  exit 0
fi

# --- Read event JSON from stdin ---
INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# --- Normalize to basename and lowercase for matching ---
BASENAME=$(basename "$FILE_PATH")
BASENAME_LOWER=$(echo "$BASENAME" | tr '[:upper:]' '[:lower:]')
FILE_PATH_LOWER=$(echo "$FILE_PATH" | tr '[:upper:]' '[:lower:]')

# --- Check protected patterns ---

# Exact dotenv files
case "$BASENAME_LOWER" in
  .env|.env.local|.env.production|.env.staging|.env.development|.env.test)
    echo "Blocked: $FILE_PATH is a protected file. Reason: environment config files must not be modified by agents. If you need to modify it, ask the user first." >&2
    exit 2
    ;;
esac

# Credential files
case "$BASENAME_LOWER" in
  credentials.json|credentials.yaml|credentials.yml|service-account.json)
    echo "Blocked: $FILE_PATH is a protected file. Reason: credential files must not be modified by agents. If you need to modify it, ask the user first." >&2
    exit 2
    ;;
esac

# Private key files (*.pem, *.key)
case "$BASENAME_LOWER" in
  *.pem|*.key)
    echo "Blocked: $FILE_PATH is a protected file. Reason: private key files must not be modified by agents. If you need to modify it, ask the user first." >&2
    exit 2
    ;;
esac

# Lock files (*.lock, package-lock.json)
case "$BASENAME_LOWER" in
  *.lock|package-lock.json)
    echo "Blocked: $FILE_PATH is a protected file. Reason: lock files are auto-generated and must not be edited manually. If you need to modify it, ask the user first." >&2
    exit 2
    ;;
esac

# .git/ directory
if [[ "$FILE_PATH" == .git/* || "$FILE_PATH" == */.git/* ]]; then
  echo "Blocked: $FILE_PATH is a protected file. Reason: .git directory internals must not be modified. If you need to modify it, ask the user first." >&2
  exit 2
fi

# Paths containing "secret" or "credential" (case-insensitive)
if [[ "$FILE_PATH_LOWER" == *secret* || "$FILE_PATH_LOWER" == *credential* ]]; then
  echo "Blocked: $FILE_PATH is a protected file. Reason: files containing 'secret' or 'credential' in the path are protected. If you need to modify it, ask the user first." >&2
  exit 2
fi

# --- Not protected: allow ---
exit 0
