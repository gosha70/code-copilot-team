#!/bin/bash
# setup.sh — Install Aider adapter conventions into a target project
#
# Usage:
#   ./adapters/aider/setup.sh <project-dir>        # install to project
#   ./adapters/aider/setup.sh --sync <project-dir>  # regenerate then install

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
  echo "Copies CONVENTIONS.md into the target project."
  exit 1
fi

# ── Regenerate if --sync ───────────────────────────────────
if $SYNC; then
  echo "[sync] Regenerating adapter configs..."
  bash "$REPO_DIR/scripts/generate.sh"
fi

# ── Install ────────────────────────────────────────────────
echo "=== Installing Aider conventions to $TARGET ==="

if [[ -f "$SCRIPT_DIR/CONVENTIONS.md" ]]; then
  cp "$SCRIPT_DIR/CONVENTIONS.md" "$TARGET/CONVENTIONS.md"
  echo "  Installed CONVENTIONS.md"
else
  echo "[WARN] CONVENTIONS.md not found. Run ./scripts/generate.sh first."
fi

echo "=== Aider setup complete ==="
