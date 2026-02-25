#!/bin/bash
# setup.sh — Install Cursor adapter rules into a target project
#
# Usage:
#   ./adapters/cursor/setup.sh <project-dir>     # install to project
#   ./adapters/cursor/setup.sh --sync <project-dir>  # regenerate then install

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
  echo "Copies .cursor/rules/*.mdc into the target project."
  exit 1
fi

# ── Regenerate if --sync ───────────────────────────────────
if $SYNC; then
  echo "[sync] Regenerating adapter configs..."
  bash "$REPO_DIR/scripts/generate.sh"
fi

# ── Install ────────────────────────────────────────────────
echo "=== Installing Cursor rules to $TARGET ==="

mkdir -p "$TARGET/.cursor/rules"

if ls "$SCRIPT_DIR/.cursor/rules"/*.mdc >/dev/null 2>&1; then
  cp "$SCRIPT_DIR/.cursor/rules"/*.mdc "$TARGET/.cursor/rules/"
  COUNT=$(ls "$TARGET/.cursor/rules"/*.mdc | wc -l | tr -d ' ')
  echo "  Installed $COUNT .mdc rule files"
else
  echo "[WARN] No .mdc files found. Run ./scripts/generate.sh first."
fi

echo "=== Cursor setup complete ==="
