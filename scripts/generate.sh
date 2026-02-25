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
# TODO (Cycle 3): Generate AGENTS.md from shared/rules/always/*
echo "[codex] Stub — not yet implemented"
mkdir -p "$ADAPTERS/codex"

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
