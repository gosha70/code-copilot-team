#!/usr/bin/env bash
set -euo pipefail

# protect-git.sh — PreToolUse hook (Bash matcher)
#
# Guards git commit and git push. On first attempt, blocks and instructs
# Claude to ask the user for permission. After user approval, Claude
# creates a one-time approval file and retries — the hook sees the file,
# consumes it, and allows the command through.
#
# Flow:
#   1. Claude tries git commit/push → hook blocks (exit 2)
#   2. Claude asks user for permission (shown as a confirmation prompt)
#   3. User approves → Claude runs: mkdir -p <dir> && touch <file>
#   4. Claude retries git commit/push → hook allows (exit 0)
#
# Approval files are scoped to the current git repo (or PWD) and user,
# consumed atomically via mv, and expire after MAX_AGE seconds.
# Compound commands (git commit && git push) require both approvals.
#
# Override: set HOOK_GIT_ALLOW=true to disable this guard entirely.

MAX_AGE=120  # seconds — approval expires after this

# --- Compute repo-scoped approval paths ---
APPROVAL_DIR="/tmp/.claude-git-approvals"
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")
if command -v md5 &>/dev/null; then
  REPO_HASH=$(printf '%s' "$REPO_ROOT" | md5 -q)
elif command -v md5sum &>/dev/null; then
  REPO_HASH=$(printf '%s' "$REPO_ROOT" | md5sum | cut -d' ' -f1)
else
  REPO_HASH=$(printf '%s' "$REPO_ROOT" | tr '/' '_')
fi
APPROVAL_COMMIT="$APPROVAL_DIR/commit-$(id -u)-${REPO_HASH}"
APPROVAL_PUSH="$APPROVAL_DIR/push-$(id -u)-${REPO_HASH}"

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

# --- Detect which operations are in the command ---
NEEDS_COMMIT=0
NEEDS_PUSH=0

if echo "$COMMAND_NORMALIZED" | grep -qE "${GIT_POS}commit\b"; then
  NEEDS_COMMIT=1
fi

if echo "$COMMAND_NORMALIZED" | grep -qE "${GIT_POS}push\b"; then
  NEEDS_PUSH=1
fi

# Neither commit nor push — allow
if [[ $NEEDS_COMMIT -eq 0 && $NEEDS_PUSH -eq 0 ]]; then
  exit 0
fi

# --- Helpers: peek (non-destructive) and consume (atomic via mv) ---
peek_approval() {
  local file="$1"
  [[ -f "$file" ]] || return 1
  local now file_mtime age
  now=$(date +%s)
  file_mtime=$(stat -f %m "$file" 2>/dev/null || stat -c %Y "$file" 2>/dev/null || echo 0)
  age=$(( now - file_mtime ))
  [[ $age -lt $MAX_AGE ]]
}

consume_approval() {
  local file="$1"
  local tmp="${file}.del.$$"
  mv "$file" "$tmp" 2>/dev/null || return 1
  rm -f "$tmp"
  return 0
}

# --- Check all needed approvals before consuming any ---
MISSING=()

if [[ $NEEDS_COMMIT -eq 1 ]] && ! peek_approval "$APPROVAL_COMMIT"; then
  MISSING+=("commit")
fi

if [[ $NEEDS_PUSH -eq 1 ]] && ! peek_approval "$APPROVAL_PUSH"; then
  MISSING+=("push")
fi

if [[ ${#MISSING[@]} -gt 0 ]]; then
  # Build block message listing all missing approvals
  {
    if [[ " ${MISSING[*]} " == *" commit "* && " ${MISSING[*]} " == *" push "* ]]; then
      cat <<MSG
Blocked: git commit and git push both require explicit user approval.

To proceed:
1. Show the user the diff summary, proposed commit message, and push target
2. Ask the user for permission to commit and push
3. Once approved, run this EXACT command in a NEW, SEPARATE Bash call (do not add git to this line):
   mkdir -p ${APPROVAL_DIR} && touch ${APPROVAL_COMMIT} ${APPROVAL_PUSH}
4. In another separate Bash call, retry the git commit/push command
MSG
    elif [[ " ${MISSING[*]} " == *" commit "* ]]; then
      cat <<MSG
Blocked: git commit requires explicit user approval.

To proceed:
1. Show the user the diff summary and your proposed commit message
2. Ask the user for permission to commit
3. Once approved, run this EXACT command in a NEW, SEPARATE Bash call (do not add git to this line):
   mkdir -p ${APPROVAL_DIR} && touch ${APPROVAL_COMMIT}
4. In another separate Bash call, retry the git commit command
MSG
    else
      cat <<MSG
Blocked: git push requires explicit user approval.

To proceed:
1. Tell the user what branch and remote you want to push to
2. Ask the user for permission to push
3. Once approved, run this EXACT command in a NEW, SEPARATE Bash call (do not add git to this line):
   mkdir -p ${APPROVAL_DIR} && touch ${APPROVAL_PUSH}
4. In another separate Bash call, retry the git push command
MSG
    fi
  } >&2
  exit 2
fi

# --- Consume approvals atomically — mv result is the gate, not the peek ---
# peek above confirmed files exist; we now race to be the sole consumer.
# If consume fails (another process won the race), block rather than allow.
if [[ $NEEDS_COMMIT -eq 1 ]]; then
  if ! consume_approval "$APPROVAL_COMMIT"; then
    echo "Blocked: commit approval was already used. Ask the user for a new approval and retry." >&2
    exit 2
  fi
fi

if [[ $NEEDS_PUSH -eq 1 ]]; then
  if ! consume_approval "$APPROVAL_PUSH"; then
    # Restore commit approval if consumed moments ago (compound git commit && git push race)
    [[ $NEEDS_COMMIT -eq 1 ]] && touch "$APPROVAL_COMMIT" 2>/dev/null || true
    echo "Blocked: push approval was already used. Ask the user for a new approval and retry." >&2
    exit 2
  fi
fi

exit 0
