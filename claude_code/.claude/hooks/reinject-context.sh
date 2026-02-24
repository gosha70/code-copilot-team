#!/usr/bin/env bash
set -euo pipefail

# reinject-context.sh — SessionStart hook
#
# After compaction or session start, re-injects critical project context:
# current phase, active PRD items, recent git log, and pending work.
# Outputs to stdout so Claude receives it as context.

# --- jq guard ---
if ! command -v jq &>/dev/null; then
  echo "jq not found; hook skipped. Install jq for hook support." >&2
  exit 0
fi

# --- Resolve project directory ---
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

if [[ ! -d "$PROJECT_DIR" ]]; then
  exit 0
fi

cd "$PROJECT_DIR" 2>/dev/null || exit 0

OUTPUT=""

# --- Git context ---
if command -v git &>/dev/null && git rev-parse --is-inside-work-tree &>/dev/null 2>&1; then
  BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
  RECENT_LOG=$(git log --oneline -5 2>/dev/null || echo "(no commits)")
  OUTPUT="${OUTPUT}## Git Context\n- Branch: ${BRANCH}\n- Recent commits:\n${RECENT_LOG}\n\n"
fi

# --- Active Ralph Loop PRD ---
if [[ -f "RALPH_PRD.json" ]]; then
  PENDING=$(jq -r '.stories[] | select(.passes == false) | "  - Story \(.id): \(.description)"' RALPH_PRD.json 2>/dev/null || true)
  if [[ -n "$PENDING" ]]; then
    OUTPUT="${OUTPUT}## Ralph Loop — Pending Stories\n${PENDING}\n\n"
  fi
  COMPLETED=$(jq '[.stories[] | select(.passes == true)] | length' RALPH_PRD.json 2>/dev/null || echo "?")
  TOTAL=$(jq '[.stories[]] | length' RALPH_PRD.json 2>/dev/null || echo "?")
  OUTPUT="${OUTPUT}Progress: ${COMPLETED}/${TOTAL} stories complete\n\n"
fi

# --- Ralph Loop progress (last entry) ---
if [[ -f "RALPH_PROGRESS.md" ]]; then
  LAST_ENTRY=$(tail -n 20 RALPH_PROGRESS.md 2>/dev/null | grep -A 20 "^## Iteration" | tail -n 15)
  if [[ -n "$LAST_ENTRY" ]]; then
    OUTPUT="${OUTPUT}## Last Ralph Loop Iteration\n${LAST_ENTRY}\n\n"
  fi
fi

# --- Pending work from doc_internal ---
if [[ -f "doc_internal/TODO.md" ]]; then
  TODO_SUMMARY=$(head -n 30 doc_internal/TODO.md 2>/dev/null)
  OUTPUT="${OUTPUT}## Pending Work (doc_internal/TODO.md)\n${TODO_SUMMARY}\n\n"
fi

# --- Phase recap (most recent) ---
LATEST_RECAP=$(ls -t doc_internal/phase-*-recap.md docs/phase-*-recap.md 2>/dev/null | head -1 || true)
if [[ -n "${LATEST_RECAP:-}" ]] && [[ -f "$LATEST_RECAP" ]]; then
  RECAP_HEADER=$(head -n 10 "$LATEST_RECAP" 2>/dev/null)
  OUTPUT="${OUTPUT}## Latest Phase Recap (${LATEST_RECAP})\n${RECAP_HEADER}\n\n"
fi

# --- GCC memory (if present) ---
if [[ -d ".gcc" ]]; then
  GCC_OUTPUT=""
  # Project roadmap from main.md
  if [[ -f ".gcc/main.md" ]]; then
    ROADMAP=$(head -n 20 .gcc/main.md 2>/dev/null)
    if [[ -n "$ROADMAP" ]]; then
      GCC_OUTPUT="${GCC_OUTPUT}### Roadmap (main.md)\n${ROADMAP}\n\n"
    fi
  fi
  # Latest commit entry from the most recent branch
  LATEST_COMMIT=$(ls -t .gcc/*/commit.md 2>/dev/null | head -1 || true)
  if [[ -n "${LATEST_COMMIT:-}" ]] && [[ -f "$LATEST_COMMIT" ]]; then
    # Get last commit entry (entries separated by blank lines with --- or ## headings)
    LAST_ENTRY=$(tail -n 20 "$LATEST_COMMIT" 2>/dev/null)
    if [[ -n "$LAST_ENTRY" ]]; then
      GCC_OUTPUT="${GCC_OUTPUT}### Recent Progress (${LATEST_COMMIT})\n${LAST_ENTRY}\n\n"
    fi
  fi
  if [[ -n "$GCC_OUTPUT" ]]; then
    OUTPUT="${OUTPUT}## GCC Memory (auto-injected)\n${GCC_OUTPUT}"
  fi
fi

# --- Output if we found anything ---
if [[ -n "$OUTPUT" ]]; then
  echo "--- Session Context (auto-injected) ---"
  printf '%b' "$OUTPUT"
  echo "--- End Session Context ---"
fi

exit 0
