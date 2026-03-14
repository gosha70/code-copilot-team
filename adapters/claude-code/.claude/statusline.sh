#!/bin/bash
# Claude Code status line — single-line ops dashboard
# Shows: [Model] agent | branch +staged ~modified | project | ctx% $cost +add/-del duration
#
# Installed by: setup.sh
# Config in:    ~/.claude/settings.json → statusLine
# Docs:         https://code.claude.com/docs/en/statusline

input=$(cat)

# --- Extract fields from JSON ---
MODEL=$(echo "$input" | jq -r '.model.display_name // "?"')
AGENT=$(echo "$input" | jq -r '.agent.name // empty')
DIR=$(basename "$(echo "$input" | jq -r '.workspace.current_dir // .cwd')")
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
DURATION_MS=$(echo "$input" | jq -r '.cost.total_duration_ms // 0')
LINES_ADD=$(echo "$input" | jq -r '.cost.total_lines_added // 0')
LINES_DEL=$(echo "$input" | jq -r '.cost.total_lines_removed // 0')
WT_NAME=$(echo "$input" | jq -r '.worktree.name // empty')

# --- Git info (cached per workspace for performance) ---
WORKSPACE=$(echo "$input" | jq -r '.workspace.current_dir // .cwd')
CACHE_KEY=$(printf '%s' "$WORKSPACE" | cksum | cut -d' ' -f1)
CACHE_FILE="/tmp/claude-statusline-git-${CACHE_KEY}"
CACHE_MAX_AGE=5

cache_is_stale() {
  [ ! -f "$CACHE_FILE" ] || \
  [ $(($(date +%s) - $(stat -f %m "$CACHE_FILE" 2>/dev/null || stat -c %Y "$CACHE_FILE" 2>/dev/null || echo 0))) -gt $CACHE_MAX_AGE ]
}

if cache_is_stale; then
  if git -C "$WORKSPACE" rev-parse --git-dir > /dev/null 2>&1; then
    BRANCH=$(git -C "$WORKSPACE" branch --show-current 2>/dev/null)
    STAGED=$(git -C "$WORKSPACE" diff --cached --numstat 2>/dev/null | wc -l | tr -d ' ')
    MODIFIED=$(git -C "$WORKSPACE" diff --numstat 2>/dev/null | wc -l | tr -d ' ')
    echo "${BRANCH}|${STAGED}|${MODIFIED}" > "$CACHE_FILE"
  else
    echo "||" > "$CACHE_FILE"
  fi
fi

IFS='|' read -r BRANCH STAGED MODIFIED < "$CACHE_FILE"

# --- Build single line ---
OUT="[${MODEL}]"
[ -n "$AGENT" ] && OUT="${OUT} ${AGENT}"

# Git
if [ -n "$BRANCH" ]; then
  GIT="${BRANCH}"
  [ "$STAGED" -gt 0 ] 2>/dev/null && GIT="${GIT} +${STAGED}"
  [ "$MODIFIED" -gt 0 ] 2>/dev/null && GIT="${GIT} ~${MODIFIED}"
  OUT="${OUT} | ${GIT}"
fi

# Worktree or project
if [ -n "$WT_NAME" ]; then
  OUT="${OUT} | wt:${WT_NAME}"
else
  OUT="${OUT} | ${DIR}"
fi

# Context + cost + lines + duration
COST_FMT=$(printf '$%.2f' "$COST")
MINS=$((DURATION_MS / 60000))
SECS=$(((DURATION_MS % 60000) / 1000))
OUT="${OUT} | ${PCT}% ${COST_FMT} +${LINES_ADD}/-${LINES_DEL} ${MINS}m${SECS}s"

echo "$OUT"
