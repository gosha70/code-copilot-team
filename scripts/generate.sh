#!/bin/bash
# generate.sh — Build tool-specific adapter configs from shared/ content
#
# Reads from:   shared/rules/always/*.md, shared/rules/on-demand/*.md
# Writes to:    adapters/<tool>/  (generated configs, committed to repo)
#
# Run after modifying shared/ content, then commit the generated outputs.
# CI verifies: git diff --exit-code adapters/ (no drift allowed).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$SCRIPT_DIR/.."
SHARED="$REPO_DIR/shared/rules"
ADAPTERS="$REPO_DIR/adapters"

echo "=== Generating adapter configs from shared/ ==="

# ── Claude Code ──────────────────────────────────────────────
# Claude Code uses direct symlinks + file copies from shared/.
# No generation needed — setup.sh reads shared/ at install time.
echo "[claude-code] No generation needed (reads shared/ directly)"

# ── Codex ────────────────────────────────────────────────────
# Generate AGENTS.md by concatenating shared/rules/always/* with on-demand TOC
echo "[codex] Generating AGENTS.md..."
CODEX_DIR="$ADAPTERS/codex"
AGENTS_MD="$CODEX_DIR/AGENTS.md"
mkdir -p "$CODEX_DIR"

{
  echo "# Codex Agent Instructions"
  echo ""
  echo "Auto-generated from shared/rules/always/. Do not edit directly."
  echo "Regenerate with: ./scripts/generate.sh"
  echo ""
  echo "---"
  echo ""

  # Concatenate all always-on rules
  for f in "$SHARED/always"/*.md; do
    cat "$f"
    echo ""
    echo "---"
    echo ""
  done

  # Append on-demand rules reference
  echo "## On-Demand Rules Reference"
  echo ""
  echo "The following rules are loaded by skills when relevant. Invoke the"
  echo "corresponding skill to apply them."
  echo ""
  echo "| Rule | Used By |"
  echo "|------|---------|"
  for f in "$SHARED/on-demand"/*.md; do
    name="$(basename "$f" .md)"
    # Map rules to skills
    case "$name" in
      ralph-loop|environment-setup|stack-constraints|phase-workflow)
        skill="build" ;;
      clarification-protocol)
        skill="plan" ;;
      integration-testing)
        skill="review" ;;
      token-efficiency)
        skill="research" ;;
      gcc-protocol)
        skill="all (optional)" ;;
      agent-team-protocol|team-lead-efficiency)
        skill="*(Claude-only, not used in Codex)*" ;;
      *)
        skill="—" ;;
    esac
    echo "| \`$name\` | $skill |"
  done
  echo ""
} > "$AGENTS_MD"

# Verify size limit (32 KiB = 32768 bytes)
SIZE=$(wc -c < "$AGENTS_MD" | tr -d ' ')
if [[ "$SIZE" -gt 32768 ]]; then
  echo "[codex] WARNING: AGENTS.md is $SIZE bytes (limit: 32768)"
  exit 1
fi
echo "[codex] AGENTS.md generated ($SIZE bytes)"

# ── Cursor ───────────────────────────────────────────────────
# TODO (Cycle 4): Generate .mdc files with frontmatter from shared/rules/always/*
echo "[cursor] Stub — not yet implemented"
mkdir -p "$ADAPTERS/cursor"

# ── GitHub Copilot ───────────────────────────────────────────
# TODO (Cycle 4): Generate copilot-instructions.md from shared/rules/always/*
echo "[github-copilot] Stub — not yet implemented"
mkdir -p "$ADAPTERS/github-copilot"

# ── Windsurf ─────────────────────────────────────────────────
# TODO (Cycle 5): Generate rules.md from shared/rules/always/*
echo "[windsurf] Stub — not yet implemented"
mkdir -p "$ADAPTERS/windsurf"

# ── Aider ────────────────────────────────────────────────────
# TODO (Cycle 5): Generate CONVENTIONS.md from shared/rules/always/*
echo "[aider] Stub — not yet implemented"
mkdir -p "$ADAPTERS/aider"

echo "=== Done ==="
