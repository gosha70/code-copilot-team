#!/bin/bash
# setup.sh — Install Codex adapter to ~/.codex/
#
# Usage:
#   ./adapters/codex/setup.sh           # install to ~/.codex/
#   ./adapters/codex/setup.sh --sync    # regenerate AGENTS.md then install

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")" && pwd)"
REPO_DIR="$SCRIPT_DIR/../.."
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"

# ── Flags ──────────────────────────────────────────────────
SYNC=false
for arg in "$@"; do
  case "$arg" in
    --sync) SYNC=true ;;
    *) echo "[WARN] Unknown flag: $arg" ;;
  esac
done

# ── Regenerate if --sync ───────────────────────────────────
if $SYNC; then
  echo "[sync] Regenerating adapter configs..."
  bash "$REPO_DIR/scripts/generate.sh"
fi

# ── Install ────────────────────────────────────────────────
echo "=== Installing Codex adapter to $CODEX_HOME ==="

mkdir -p "$CODEX_HOME"
mkdir -p "$CODEX_HOME/.agents/skills"

# AGENTS.md
if [[ -f "$SCRIPT_DIR/AGENTS.md" ]]; then
  cp "$SCRIPT_DIR/AGENTS.md" "$CODEX_HOME/AGENTS.md"
  echo "  Installed AGENTS.md"
else
  echo "[WARN] AGENTS.md not found. Run ./scripts/generate.sh first."
fi

# config.toml
cp "$SCRIPT_DIR/config.toml" "$CODEX_HOME/config.toml"
echo "  Installed config.toml"

# Skills
for skill_dir in "$SCRIPT_DIR/.agents/skills"/*/; do
  skill_name="$(basename "$skill_dir")"
  mkdir -p "$CODEX_HOME/.agents/skills/$skill_name"
  cp "$skill_dir/SKILL.md" "$CODEX_HOME/.agents/skills/$skill_name/SKILL.md"
  echo "  Installed skill: $skill_name"
done

echo "=== Codex setup complete ==="
echo ""
echo "Verify: ls ~/.codex/AGENTS.md ~/.codex/.agents/skills/*/SKILL.md"
