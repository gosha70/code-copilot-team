#!/bin/bash
# setup.sh — Install Windsurf adapter rules into a target project
#
# Usage:
#   ./adapters/windsurf/setup.sh <project-dir>        # install to project
#   ./adapters/windsurf/setup.sh --sync <project-dir>  # regenerate then install

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
  echo "Copies .windsurf/rules/rules.md into the target project."
  exit 1
fi

# ── Regenerate if --sync ───────────────────────────────────
if $SYNC; then
  echo "[sync] Regenerating adapter configs..."
  bash "$REPO_DIR/scripts/generate.sh"
fi

# ── Install ────────────────────────────────────────────────
echo "=== Installing Windsurf rules to $TARGET ==="

mkdir -p "$TARGET/.windsurf/rules"

if [[ -f "$SCRIPT_DIR/.windsurf/rules/rules.md" ]]; then
  cp "$SCRIPT_DIR/.windsurf/rules/rules.md" "$TARGET/.windsurf/rules/rules.md"
  echo "  Installed rules.md"
else
  echo "[WARN] rules.md not found. Run ./scripts/generate.sh first."
fi

echo "=== Windsurf setup complete ==="
