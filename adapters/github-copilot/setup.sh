#!/bin/bash
# setup.sh — Install GitHub Copilot adapter instructions into a target project
#
# Usage:
#   ./adapters/github-copilot/setup.sh <project-dir>     # install to project
#   ./adapters/github-copilot/setup.sh --sync <project-dir>  # regenerate then install

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")" && pwd)"
REPO_DIR="$SCRIPT_DIR/../.."

# ── Flags ──────────────────────────────────────────────────
SYNC=false
TARGET=""
for arg in "$@"; do
  case "$arg" in
    --sync) SYNC=true ;;
    *) TARGET="$arg" ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  echo "Usage: $0 [--sync] <project-dir>"
  echo ""
  echo "Copies .github/copilot-instructions.md and .github/instructions/"
  echo "into the target project."
  exit 1
fi

# ── Regenerate if --sync ───────────────────────────────────
if $SYNC; then
  echo "[sync] Regenerating adapter configs..."
  bash "$REPO_DIR/scripts/generate.sh"
fi

# ── Install ────────────────────────────────────────────────
echo "=== Installing GitHub Copilot instructions to $TARGET ==="

mkdir -p "$TARGET/.github/instructions"

# Always-on instructions
if [[ -f "$SCRIPT_DIR/.github/copilot-instructions.md" ]]; then
  cp "$SCRIPT_DIR/.github/copilot-instructions.md" "$TARGET/.github/copilot-instructions.md"
  echo "  Installed copilot-instructions.md"
else
  echo "[WARN] copilot-instructions.md not found. Run ./scripts/generate.sh first."
fi

# On-demand instructions
if ls "$SCRIPT_DIR/.github/instructions"/*.instructions.md >/dev/null 2>&1; then
  cp "$SCRIPT_DIR/.github/instructions"/*.instructions.md "$TARGET/.github/instructions/"
  COUNT=$(ls "$TARGET/.github/instructions"/*.instructions.md | wc -l | tr -d ' ')
  echo "  Installed $COUNT on-demand instruction files"
else
  echo "[WARN] No instruction files found. Run ./scripts/generate.sh first."
fi

echo "=== GitHub Copilot setup complete ==="
