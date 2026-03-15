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

# --- Strip non-executing content before matching ---

# 1. Remove heredoc bodies (lines between <<DELIM and DELIM)
STRIPPED=$(printf '%s\n' "$COMMAND" | awk '
  BEGIN { delim="" }
  delim == "" {
    s = $0
    if (match(s, /<<-?[[:space:]]*\\?/)) {
      rest = substr(s, RSTART + RLENGTH)
      sub(/^["'"'"'"]/, "", rest)
      if (match(rest, /^[A-Za-z_][A-Za-z_0-9]*/)) {
        delim = substr(rest, RSTART, RLENGTH)
      }
    }
    print
    next
  }
  {
    line = $0
    sub(/^[[:space:]]+/, "", line)
    sub(/[[:space:]]+$/, "", line)
    if (line == delim) { delim=""; next }
    next
  }
')

# 2. Remove single-quoted strings
STRIPPED=$(printf '%s\n' "$STRIPPED" | sed "s/'[^']*'//g")

# 3. Remove literal text inside double-quoted strings, but preserve
#    command substitutions ($(...) and `...`) which still execute.
STRIPPED=$(printf '%s\n' "$STRIPPED" | awk '{
  out = ""
  s = $0
  while (s != "") {
    # Find next double quote
    qi = index(s, "\"")
    if (qi == 0) { out = out s; break }
    # Copy everything before the opening quote
    out = out substr(s, 1, qi - 1)
    s = substr(s, qi + 1)
    # Walk inside the double-quoted string
    while (s != "") {
      # Closing quote
      if (substr(s, 1, 1) == "\"") { s = substr(s, 2); break }
      # Escaped character — skip both
      if (substr(s, 1, 1) == "\\") { s = substr(s, 3); continue }
      # $(...) — preserve (executable)
      if (substr(s, 1, 2) == "$(") {
        depth = 1; j = 3
        while (j <= length(s) && depth > 0) {
          c = substr(s, j, 1)
          if (c == "(") depth++
          else if (c == ")") depth--
          j++
        }
        out = out substr(s, 1, j - 1)
        s = substr(s, j)
        continue
      }
      # Backtick substitution — preserve (executable)
      if (substr(s, 1, 1) == "`") {
        j = index(substr(s, 2), "`")
        if (j > 0) {
          out = out substr(s, 1, j + 1)
          s = substr(s, j + 2)
        } else {
          out = out s; s = ""; break
        }
        continue
      }
      # Plain literal character — discard
      s = substr(s, 2)
    }
  }
  print out
}')

# --- Normalize: convert newlines to ; (preserving command boundaries),
#     then collapse repeated spaces ---
COMMAND_NORMALIZED=$(printf '%s\n' "$STRIPPED" | tr '\n' ';' | sed 's/  */ /g; s/^ //')

# --- Match pattern ---
# Matches git commit/push at: start of string, after && ; || ( ` $(,
# with optional transparent wrappers that may stack in any order:
# env (with recognized flags/args), command, builtin, exec, and VAR=value.
ENV_PREFIX='env\s+(((-i|--ignore-environment|-0|--null)\s+)|((-u|--unset|-C|--chdir|-S|--split-string)\s+\S+\s+)|(--(unset|chdir|split-string)=\S+\s+)|(--\s+)|(\w+=\S*\s+))*'
TRANSPARENT_PREFIX="(${ENV_PREFIX}|(command|builtin|exec)\s+|\w+=\S*\s+)"
GIT_POS="(^|&&\s*|;\s*|\|\|\s*|\(\s*|\`\s*|\$\(\s*)(${TRANSPARENT_PREFIX})*git\s+"

# --- Check for git commit in a command position ---
if echo "$COMMAND_NORMALIZED" | grep -qE "${GIT_POS}commit\b"; then
  echo "Blocked: git commit requires explicit user instruction. Show the diff summary first, propose a commit message, and wait for the user to say 'commit', 'yes', or 'go ahead'. Do not commit in response to questions like 'what is the commit message'." >&2
  exit 2
fi

# --- Check for git push in a command position ---
if echo "$COMMAND_NORMALIZED" | grep -qE "${GIT_POS}push\b"; then
  echo "Blocked: git push requires explicit user instruction. Never push automatically after a commit. Wait for the user to explicitly request a push." >&2
  exit 2
fi

# --- Not a git commit/push: allow ---
exit 0
